#!/usr/bin/env python
#  coding=utf-8
#  vim:ts=4:sts=4:sw=4:et
#
#  Author: Hari Sekhon
#  Date: Tue Sep 26 09:24:25 CEST 2017
#
#  https://github.com/harisekhon/nagios-plugins
#
#  License: see accompanying Hari Sekhon LICENSE file
#
#  If you're using my code you're welcome to connect with me on LinkedIn
#  and optionally send me feedback to help steer this or other code I publish
#
#  https://www.linkedin.com/in/harisekhon
#

"""

Nagios Plugin to check an Apache Ranger policy via Ranger Admin's REST API

Checks a policy by name or id is:

- present
- enabled
- has auditing (can disable audit check)
- recursive (optional)

Giving a policy ID is a much more efficient query but if you given a non-existent policy ID you will get a more generic
404 Not Found critical error result

If specifying a policy --id (which you can find via --list-policies) and also specifying a policy --name
then the name will be validated against the returned policy if one is found by targeted id query

Tested on HDP 2.6.1 (Ranger 0.7.0)

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import sys
import traceback
srcdir = os.path.abspath(os.path.dirname(__file__))
libdir = os.path.join(srcdir, 'pylib')
sys.path.append(libdir)
try:
    # pylint: disable=wrong-import-position
    from harisekhon.utils import isList
    from harisekhon.utils import ERRORS, CriticalError, UnknownError, jsonpp
    from harisekhon import RestNagiosPlugin
except ImportError as _:
    print(traceback.format_exc(), end='')
    sys.exit(4)

__author__ = 'Hari Sekhon'
__version__ = '0.1'


class CheckRangerPolicy(RestNagiosPlugin):

    def __init__(self):
        # Python 2.x
        super(CheckRangerPolicy, self).__init__()
        # Python 3.x
        # super().__init__()
        self.name = ['Hadoop Ranger', 'Ranger', 'Hadoop']
        self.path = '/service/public/api/policy'
        self.default_port = 6080
        self.json = True
        self.auth = True
        self.msg = 'Ranger Message Not Defined'
        self.policy_name = None
        self.policy_id = None
        self.no_audit = False
        self.recursive = False
        self.list_policies = False

    def add_options(self):
        super(CheckRangerPolicy, self).add_options()
        self.add_opt('-o', '--name', help='Policy name to expect to find')
        self.add_opt('-i', '--id', help='Policy ID to expect to find')
        self.add_opt('-a', '--no-audit', action='store_true', help='Do not require auditing to be enabled')
        self.add_opt('-r', '--recursive', action='store_true', help='Checks the policy is set to recursive')
        self.add_opt('-l', '--list-policies', action='store_true', help='List Ranger policies and exit')
        #self.add_thresholds()

    def process_options(self):
        super(CheckRangerPolicy, self).process_options()

        self.policy_name = self.get_opt('name')
        self.policy_id = self.get_opt('id')
        self.no_audit = self.get_opt('no_audit')
        self.recursive = self.get_opt('recursive')
        self.list_policies = self.get_opt('list_policies')

        if not self.list_policies:
            if not self.policy_name and not self.policy_id:
                self.usage('--policy name / --policy-id is not defined')

        if self.policy_id and not self.list_policies:
            self.path += '/{0}'.format(self.policy_id)

        # TODO: iterate over pages...
        # might be more efficient if your policy is found in the first few pages
        # better solution would be to simply pass the policy ID to this plugin to limit the query
        # causes time outs with 3000 policies
        #self.path += '?pageSize=999999'

        #self.validate_thresholds(optional=True)

    # TODO: extract msgDesc from json error response

    def parse_json(self, json_data):
        policy = None
        if self.policy_id:
            policy = json_data
            policy_list = [policy]
        if not self.policy_id or self.list_policies:
            policy_list = json_data['vXPolicies']
        if not policy_list:
            raise CriticalError('no Ranger policies found!')
        host_info = ''
        if self.verbose:
            host_info = " at '{0}:{1}'".format(self.host, self.port)
        if not isList(policy_list):
            raise UnknownError("non-list returned for json_data[vXPolicies] by Ranger{0}"\
                               .format(host_info))
        ##########################
        #num_apps = len(app_list)
        #log.info("processing {0:d} running apps returned by Yarn Resource Manager{1}".format(num_apps, host_info))
        #assert num_apps <= self.limit
        if self.list_policies:
            self.print_policies(policy_list)
            sys.exit(ERRORS['UNKNOWN'])

        if policy is None and self.policy_name:
            for _ in policy_list:
                if _['policyName'] == self.policy_name:
                    policy = _
                    break
        # this won't apply when --policy-id is given as it's a targeted query that will get 404 before this
        if not policy:
            raise CriticalError("no matching policy found with name '{name}' in policy list "\
                                .format(name=self.policy_name) +
                                "returned by Ranger{host_info}".format(host_info=host_info))

        self.check_policy(policy)

    def check_policy(self, policy):
        policy_name = policy['policyName']
        policy_id = policy['id']
        if self.policy_id:
            assert str(policy_id) == str(self.policy_id)
        self.msg = "Ranger policy id '{0}' name '{1}'".format(policy_id, policy_name)
        if self.policy_name is not None and self.policy_name != policy_name:
            self.critical()
            self.msg += " (expected '{0}')".format(self.policy_name)
        enabled = policy['isEnabled']
        auditing = policy['isAuditEnabled']
        recursive = policy['isRecursive']
        self.msg += ', enabled = {0}'.format(enabled)
        if not enabled:
            self.critical()
            self.msg += ' (expected True)'
        self.msg += ', auditing = {0}'.format(auditing)
        if not auditing and not self.no_audit:
            self.critical()
            self.msg += ' (expected True)'
        self.msg += ', recursive = {0}'.format(recursive)
        if self.recursive and not recursive:
            self.critical()
            self.msg += ' (expected True)'

    @staticmethod
    def print_policies(policy_list):
        cols = {
            'Name': 'policyName',
            'RepoName': 'repositoryName',
            'RepoType': 'repositoryType',
            'Description': 'description',
            'Enabled': 'isEnabled',
            'Audit': 'isAuditEnabled',
            'Recursive': 'isRecursive',
            'Id': 'id',
        }
        widths = {}
        for col in cols:
            widths[col] = len(col)
        for _ in policy_list:
            print(jsonpp(_))
            for col in cols:
                if col == 'Description':
                    continue
                if not col in widths:
                    widths[col] = 0
                width = len(str(_[cols[col]]))
                if width > widths[col]:
                    widths[col] = width
        total_width = 0
        columns = ('Id', 'Name', 'RepoName', 'RepoType', 'Enabled', 'Audit', 'Recursive', 'Description')
        for heading in columns:
            total_width += widths[heading] + 2
        print('=' * total_width)
        for heading in columns:
            print('{0:{1}}  '.format(heading, widths[heading]), end='')
        print()
        print('=' * total_width)
        for _ in policy_list:
            for col in columns:
                print('{0:{1}}  '.format(_[cols[col]], widths[col]), end='')
            print()


if __name__ == '__main__':
    CheckRangerPolicy().main()
