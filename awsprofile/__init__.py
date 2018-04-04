#!/usr/bin/env python
# There is a standard way to configure clients to assume role for a profile. See:
#     http://docs.aws.amazon.com/cli/latest/topic/config-vars.html#using-aws-iam-roles
# However, not all AWS SDKs support this AssumeRole configuration (yet).
#
# This script processes the configuration using boto (which supports this) and exports
#     environment variables which are standardised for use with less current SDKs
import argparse
import json
import os
import sys
import subprocess

import botocore.session

from awscli.utils import json_encoder
from awscli.customizations.assumerole import JSONFileCache

# JSONFileCache from awscli does not serialize datetime, add json_encoder support
class FixedJSONFileCache(JSONFileCache):
    def __setitem__(self, cache_key, value):
        full_key = self._convert_cache_key(cache_key)
        try:
            file_content = json.dumps(value, default=json_encoder)
        except (TypeError, ValueError):
            raise ValueError("Value cannot be cached, must be "
                             "JSON serializable: %s" % value)
        if not os.path.isdir(self._working_dir):
            os.makedirs(self._working_dir)
        with os.fdopen(os.open(full_key,
                               os.O_WRONLY | os.O_CREAT, 0o600), 'w') as f:
            f.truncate()
            f.write(file_content)

def configure_cache(session):
    """ Injects caching to the session's credential provider """
    cred_chain = session.get_component('credential_provider')
    provider = cred_chain.get_provider('assume-role')
    provider.cache = FixedJSONFileCache()

def parse_args(argv=sys.argv):
    parser = argparse.ArgumentParser(
            description='Run a command under a given AWS profile.')
    parser.add_argument('profile', nargs='?', default=None,
                        help='AWS profile to use')
    parser.add_argument('command', metavar='...', nargs=argparse.REMAINDER,
                        help='Command to run, with any arguments')
    parser.add_argument('-e', '--export-mode', dest='export',
                        action='store_true', help=(
                            'Instead of running a command, print bash commands'
                            ' to export the appropriate AWS environment'
                            ' variables, e.g. eval $(aws-profile -e my_profile)'
                        )
                       )
    return parser.parse_args()

def unset_profile(env):
    '''
    Unset AWS profile variables os that the command doesn't try (possibly
    incorrectly) to use the profile itself.
    '''
    env = os.environ.copy()
    env.pop('AWS_DEFAULT_PROFILE', None)
    env.pop('AWS_PROFILE', None)

def session_vars(session):
    '''
    Set environment variables for region, access and secret keys, and
    optionally security or session token, as determined by the config and
    credentials of the boto session.
    '''
    config = session.get_scoped_config()
    creds = session.get_credentials()
    vars_dict = {
        'AWS_DEFAULT_REGION': config.get('region'),
        'AWS_REGION': config.get('region'),
        'AWS_ACCESS_KEY_ID': creds.access_key,
        'AWS_SECRET_ACCESS_KEY': creds.secret_key
    }
    if creds.token:
        if os.getenv('AWS_TOKEN_TYPE') == 'security':
            vars_dict['AWS_SECURITY_TOKEN'] = creds.token
        else:
            vars_dict['AWS_SESSION_TOKEN'] = creds.token
    return vars_dict

def main():
    args = parse_args()

    session = botocore.session.Session(profile=args.profile)
    configure_cache(session)

    aws_vars = session_vars(session)
    if args.export:
        print('unset AWS_DEFAULT_PROFILE;')
        print('unset AWS_PROFILE;')
        for var, value in aws_vars.items():
            print('export {var}={value};'.format(var=var, value=value))
    else:
        env = os.environ.copy()
        unset_profile(env)
        env.update(aws_vars)
        returncode = subprocess.call(
            args.command, env=env, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr
        )

        exit(os.WEXITSTATUS(returncode))

if __name__ == '__main__':
    main()
