#!/usr/bin/python
#
# Copyright (c) 2015, Arista Networks, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#   Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#
#   Neither the name of Arista Networks nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL ARISTA NETWORKS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
DOCUMENTATION = """
---
module: eos_user
short_description: Manage CLI users on Arista nodes
description:
  - The eos_user module helps manage CLI users on your Arista nodes. You can
    create, delete and modify users along with their passwords.
version_added: 1.2.0
category: System
author: Arista EOS+
requirements:
  - Arista EOS 4.13.7M or later with command API enabled
  - Python Client for eAPI 0.4.0 or later
  - Cleartext passwords are not accepted in playbooks
notes:
  - All configuration is idempotent unless otherwise specified
  - Supports eos metaparameters for using the eAPI transport
  - Supports stateful resource configuration.
options:
  name:
    description:
      - "The unique username. The username must adhere to certain format
        guidelines. Valid usernames begin with A-Z, a-z, or 0-9 and may also
        contain any of these characters: @#$%^&*-_= +;<>,.~|"
    required: true
    default: null
    choices: []
    aliases: []
    version_added: 1.2.0
  nopassword:
    description:
      - The nopassword key is used to create a user with no password
        assigned. This attribute is mutually exclusive with secret and
        encryption.
    required: false
    default: false
    choices: ['True', 'False']
    aliases: []
    version_added: 1.2.0
  encryption:
    description:
      - Defines the encryption format of the password provided in the
        corresponding secret key. Note that cleartext passwords are allowed
        via manual CLI user creation but are not supported in this module due
        to security concerns and idempotency.
    required: false
    default: null
    choices: ['md5', 'sha512']
    aliases: []
    version_added: 1.2.0
  secret:
    description:
      - This key is used in conjunction with encryption. The value should be
        a hashed password that was previously generated.
    required: false
    default: null
    choices: []
    aliases: []
    version_added: 1.2.0
  role:
    description:
      - Configures the role assigned to the user. The EOS default for this
        attribute is managed with aaa authorization policy local default-role;
        this is typically the network-operator role.
    required: false
    default: null
    choices: []
    aliases: []
    version_added: 1.2.0
  privilege:
    description:
      - Configures the privilege level for the user. Permitted values are
        integers between 0 and 15. The EOS default privilege is 1.
    required: false
    default: null
    choices: []
    aliases: []
    version_added: 1.2.0
  sshkey:
    description:
      - Configures an sshkey for the CLI user. This sshkey will end up in
        /home/USER/.ssh/authorized_keys.  Typically this is the public key
        from the client SSH node.
    required: false
    default: null
    choices: []
    aliases: []
    version_added: 1.2.0
"""

EXAMPLES = """

- name: Create simple user with no assigned password
  eos_user: name=simpletom nopassword=true

- name: Create user with MD5 password
  eos_user: name=securetom encryption=md5
            secret=$1$J0auuPhz$Pkr5NnHssW.Jqlk17Ylpk0

- name: Create user with SHA512 password (passwd truncated in eg)
  eos_user: name=securetom encryption=sha512
            secret=$6$somesalt$rkDq7Az4Efjo

- name: Remove user
  eos_user: name=securetom state=absent

- name: Create user with privilege level 10
  eos_user: name=securetom encryption=sha512
            secret=$6$somesalt$rkDq7Az4Efjo
            privilege=10

- name: Create user with role network-admin
  eos_user: name=securetom encryption=sha512
            secret=$6$somesalt$rkDq7Az4Efjo
            privilege=10 role=network-admin

- name: Add an SSH key with a user no password
  eos_user: name=sshkeytom nopassword=true
            sshkey='ssh-rsa somesshkey'

- name: Remove SSH key with a user no password
  eos_user: name=sshkeytom nopassword=true
            sshkey=''
"""
#<<EOS_COMMON_MODULE_START>>

import syslog
import collections

from ansible.module_utils.basic import *

try:
    import pyeapi
    PYEAPI_AVAILABLE = True
except ImportError:
    PYEAPI_AVAILABLE = False

DEFAULT_SYSLOG_PRIORITY = syslog.LOG_NOTICE
DEFAULT_CONNECTION = 'localhost'
TRANSPORTS = ['socket', 'http', 'https', 'http_local']

class EosConnection(object):

    __attributes__ = ['username', 'password', 'host', 'transport', 'port']

    def __init__(self, **kwargs):
        self.connection = kwargs['connection']
        self.transport = kwargs.get('transport')

        self.username = kwargs.get('username')
        self.password = kwargs.get('password')

        self.host = kwargs.get('host')
        self.port = kwargs.get('port')

        self.config = kwargs.get('config')

    def connect(self):
        if self.config is not None:
            pyeapi.load_config(self.config)

        config = dict()

        if self.connection is not None:
            config = pyeapi.config_for(self.connection)
            if not config:
                msg = 'Connection name "{}" not found'.format(self.connection)

        for key in self.__attributes__:
            if getattr(self, key) is not None:
                config[key] = getattr(self, key)

        if 'transport' not in config:
            raise ValueError('Connection must define a transport')

        connection = pyeapi.client.make_connection(**config)
        node = pyeapi.client.Node(connection, **config)

        try:
            node.enable('show version')
        except (pyeapi.eapilib.ConnectionError, pyeapi.eapilib.CommandError):
            raise ValueError('unable to connect to {}'.format(node))
        return node


class EosAnsibleModule(AnsibleModule):

    meta_args = {
        'config': dict(),
        'username': dict(),
        'password': dict(),
        'host': dict(),
        'connection': dict(default=DEFAULT_CONNECTION),
        'transport': dict(choices=TRANSPORTS),
        'port': dict(),
        'debug': dict(type='bool', default='false'),
        'logging': dict(type='bool', default='true')
    }

    stateful_args = {
        'state': dict(default='present', choices=['present', 'absent']),
    }

    def __init__(self, stateful=True, autorefresh=False, *args, **kwargs):

        kwargs['argument_spec'].update(self.meta_args)

        self._stateful = stateful
        if stateful:
            kwargs['argument_spec'].update(self.stateful_args)

        ## Ok, so in Ansible 2.0,
        ## AnsibleModule.__init__() sets self.params and then
        ##   calls self.log()
        ##   (through self._log_invocation())
        ##
        ## However, self.log() (overridden in EosAnsibleModule)
        ##   references self._logging
        ## and self._logging (defined in EosAnsibleModule)
        ##   references self.params.
        ##
        ## So ... I'm defining self._logging without "or self.params['logging']"
        ##   *before* AnsibleModule.__init__() to avoid a "ref before def".
        ##
        ## I verified that this works with Ansible 1.9.4 and 2.0.0.2.
        ## The only caveat is that the first log message in
        ##   AnsibleModule.__init__() won't be subject to the value of
        ##   self.params['logging'].
        self._logging = kwargs.get('logging')
        super(EosAnsibleModule, self).__init__(*args, **kwargs)

        self.result = dict(changed=False, changes=dict())

        self._debug = kwargs.get('debug') or self.boolean(self.params['debug'])
        self._logging = kwargs.get('logging') or self.params['logging']

        self.log('DEBUG flag is %s' % self._debug)

        self.debug('pyeapi_version', self.check_pyeapi())
        self.debug('stateful', self._stateful)
        self.debug('params', self.params)

        self._attributes = self.map_argument_spec()
        self.validate()
        self._autorefresh = autorefresh
        self._node = EosConnection(**self.params)
        self._node.connect()

        self._node = self.connect()
        self._instance = None

        self.desired_state = self.params['state'] if self._stateful else None
        self.exit_after_flush = kwargs.get('exit_after_flush')

    @property
    def instance(self):
        if self._instance:
            return self._instance

        func = self.func('instance')
        if not func:
            self.fail('Module does not support "instance"')

        try:
            self._instance = func(self)
        except Exception as exc:
            self.fail('instance[error]: %s' % exc.message)

        self.log("called instance: %s" % self._instance)
        return self._instance

    @property
    def attributes(self):
        return self._attributes

    @property
    def node(self):
        return self._node

    def check_pyeapi(self):
        if not PYEAPI_AVAILABLE:
            self.fail('Unable to import pyeapi, is it installed?')
        return pyeapi.__version__

    def map_argument_spec(self):
        """map_argument_spec maps only the module argument spec to attrs

        This method will map the argumentspec minus the meta_args to attrs
        and return the attrs.  This returns a dict object that includes only
        the original argspec plus the stateful_args (if self._stateful=True)

        Returns:
            dict: Returns a dict object that includes the original
                argument_spec plus stateful_args with values minus meta_args

        """
        keys = set(self.params).difference(self.meta_args)
        attrs = dict()
        attrs = dict([(k, self.params[k]) for k in self.params if k in keys])
        if 'CHECKMODE' in attrs:
            del attrs['CHECKMODE']
        return attrs

    def validate(self):
        for key, value in self.attributes.iteritems():
            func = self.func('validate_%s' % key)
            if func:
                self.attributes[key] = func(value)

    def create(self):
        if not self.check_mode:
            func = self.func('create')
            if not func:
                self.fail('Module must define "create" function')
            return self.invoke(func, self)

    def remove(self):
        if not self.check_mode:
            func = self.func('remove')
            if not func:
                self.fail('Module most define "remove" function')
            return self.invoke(func, self)

    def flush(self, exit_after_flush=False):
        self.exit_after_flush = exit_after_flush

        if self.desired_state == 'present' or not self._stateful:
            if self.instance.get('state') == 'absent':
                changed = self.create()
                self.result['changed'] = changed or True
                self.refresh()
                # After a create command, flush the running-config
                # so we get the latest for any other attributes
                self._node._running_config = None

            changeset = self.attributes.viewitems() - self.instance.viewitems()

            if self._debug:
                self.debug('desired_state', self.attributes)
                self.debug('current_state', self.instance)

            changes = self.update(changeset)
            if changes:
                self.result['changes'] = changes
                self.result['changed'] = True

            self._attributes.update(changes)

            flush = self.func('flush')
            if flush:
                self.invoke(flush, self)

        elif self.desired_state == 'absent' and self._stateful:
            if self.instance.get('state') == 'present':
                changed = self.remove()
                self.result['changed'] = changed or True

        elif self._stateful:
            if self.desired_state != self.instance.get('state'):
                func = self.func(self.desired_state)
                changed = self.invoke(func, self)
                self.result['changed'] = changed or True

        self.refresh()
        # By calling self.instance here we trigger another show running-config
        # all which causes delay.  Only if debug is enabled do we call this
        # since it will display the latest state of the object.
        if self._debug:
            self.result['instance'] = self.instance

        if self.exit_after_flush:
            self.exit()

    def update(self, changeset):
        changes = dict()
        for key, value in changeset:
            if value is not None:
                changes[key] = value
                func = self.func('set_%s' % key)
                if func and not self.check_mode:
                    try:
                        self.invoke(func, self)
                    except Exception as exc:
                        self.fail(exc.message)
        return changes

    def connect(self):
        if self.params['config']:
            pyeapi.load_config(self.params['config'])

        config = dict()

        if self.params['connection']:
            config = pyeapi.config_for(self.params['connection'])
            if not config:
                msg = 'Connection name "%s" not found' % self.params['connection']
                self.fail(msg)

        if self.params['username']:
            config['username'] = self.params['username']

        if self.params['password']:
            config['password'] = self.params['password']

        if self.params['transport']:
            config['transport'] = self.params['transport']

        if self.params['port']:
            config['port'] = self.params['port']

        if self.params['host']:
            config['host'] = self.params['host']

        if 'transport' not in config:
            self.fail('Connection must define a transport')

        connection = pyeapi.client.make_connection(**config)
        self.log('Creating connection with autorefresh=%s' % self._autorefresh)
        node = pyeapi.client.Node(connection, autorefresh=self._autorefresh,
                                  **config)

        try:
            resp = node.enable('show version')
            self.debug('eos_version', resp[0]['result']['version'])
            self.debug('eos_model', resp[0]['result']['modelName'])
        except (pyeapi.eapilib.ConnectionError, pyeapi.eapilib.CommandError):
            self.fail('unable to connect to %s' % node)
        else:
            self.log('Connected to node %s' % node)
            self.debug('node', str(node))

        return node

    def config(self, commands):
        self.result['changed'] = True
        if not self.check_mode:
            self.node.config(commands)

    def api(self, module):
        return self.node.api(module)

    def func(self, name):
        return globals().get(name)

    def invoke(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            self.fail(exc.message)

    def invoke_function(self, name, *args, **kwargs):
        func = self.func(name)
        if func:
            return self.invoke(func, *args, **kwargs)

    def fail(self, msg):
        self.invoke_function('on_fail', self)
        self.log('ERROR: %s' % msg, syslog.LOG_ERR)
        self.fail_json(msg=msg)

    def exit(self):
        self.invoke_function('on_exit', self)
        self.log('Module completed successfully')
        self.exit_json(**self.result)

    def refresh(self):
        self._instance = None

    def debug(self, key, value):
        if self._debug:
            if 'debug' not in self.result:
                self.result['debug'] = dict()
            self.result['debug'][key] = value

    def log(self, message, log_args=None, priority=None):
        if self._logging:
            syslog.openlog('ansible-eos')
            priority = priority or DEFAULT_SYSLOG_PRIORITY
            syslog.syslog(priority, str(message))

    @classmethod
    def add_state(cls, name):
        cls.stateful_args['state']['choices'].append(name)

#<<EOS_COMMON_MODULE_END>>

def instance(module):
    """ Returns properties for the specified username
    """
    name = module.attributes['name']
    result = module.node.api('users').get(name)
    _instance = dict(name=name, state='absent')
    if result:
        _instance['state'] = 'present'
        _instance['nopassword'] = result['nopassword']
        _instance['privilege'] = result['privilege']
        _instance['role'] = result['role']
        _instance['secret'] = result['secret']
        _instance['sshkey'] = result['sshkey']

        # Map secret format values 5 to md5
        if result['format'] == '5':
            _instance['encryption'] = 'md5'
        elif result['format'] == 'sha512':
            _instance['encryption'] = 'sha512'
        else:
            _instance['encryption'] = None

    return _instance


def create(module):
    """Creates a new instance of user on the node
    """
    name = module.attributes['name']
    nopassword = module.attributes['nopassword']

    if nopassword:
        module.log('Invoked create nopassword user for eos_user[%s]' % name)
        module.node.api('users').create_with_nopassword(name)
    else:
        module.log('Invoked create user with secret for eos_user[%s]' % name)
        encryption = module.attributes['encryption']
        secret = module.attributes['secret']
        module.node.api('users').create_with_secret(name, secret, encryption)


def remove(module):
    """Removes an existing user from the node
    """
    name = module.attributes['name']
    if name is 'admin':
        module.fail('Deleting username admin is prohibited.')

    module.log('Invoked remove for eos_user[%s]' % name)
    module.node.api('users').delete(name)


def set_privilege(module):
    """ Configures the privilege for the user
    """
    name = module.attributes['name']
    value = module.attributes['privilege']

    value = None if value == '' else value
    module.log('Invoked set_privilege for eos_user[%s] '
               'with value %s' % (name, value))
    module.node.api('users').set_privilege(name, value)


def set_role(module):
    """ Configures the role for the user
    """
    name = module.attributes['name']
    value = module.attributes['role']

    module.log('Invoked set_role for eos_user[%s] '
               'with value %s' % (name, value))
    if value == '':
        module.node.api('users').set_role(name, value, disable=True)
    else:
        module.node.api('users').set_role(name, value)


def set_secret(module):
    """ Configures the password for the user.
    """
    name = module.attributes['name']
    secret = module.attributes['secret']
    encryption = module.attributes['encryption']
    nopassword = module.attributes['nopassword']

    if nopassword and secret:
        module.fail('Invoked set_secret but also nopassword is True. These '
                    'arguments are mutually exclusive. Choose one.')

    if secret == '':
        module.fail('Invoked set_secret with a null value. Please enter the '
                    'the secret value.')

    if not encryption:
        module.fail('Invoked set_secret without an encryption value. Please '
                    'choose from one of the encryption choices.')

    module.log('Invoked set_secret for eos_user[%s] '
               'with secret %s and encryption %s' % (name, secret, encryption))
    module.node.api('users').create_with_secret(name, secret, encryption)


def set_sshkey(module):
    """ Configures the sshkey for the user. The user must have already between
        created.
    """
    name = module.attributes['name']
    sshkey = module.attributes['sshkey']

    module.log('Invoked set_sshkey for eos_user[%s]' % name)
    if sshkey == '':
        module.node.api('users').set_sshkey(name, sshkey, disable=True)
    else:
        module.node.api('users').set_sshkey(name, sshkey)


def main():
    """ The main module routine called when the module is run by Ansible
    """

    argument_spec = dict(
        name=dict(required=True),
        privilege=dict(required=False),
        role=dict(required=False),
        secret=dict(required=False),
        nopassword=dict(type='bool', default='false'),
        encryption=dict(choices=['md5', 'sha512']),
        sshkey=dict(required=False)
    )

    EosAnsibleModule.add_state('default')

    module = EosAnsibleModule(argument_spec=argument_spec,
                              supports_check_mode=True)

    module.flush(True)

main()