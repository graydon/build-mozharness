#!/usr/bin/env python
"""multil10n.py

Our initial [successful] attempt at a multi-locale repack happened inside
of MaemoBuildFactory.  However, this was highly buildbot-intensive,
requiring runtime step truncation/creation with large amounts of build
properties that disallowed the use of "Force Build" for any multi-locale
nightly.

To improve things, we're moving the logic slave-side where a dedicated
slave can use its cycles determining which locales to repack.
"""

import hashlib
import os
import re
import sys

# load modules from parent dir
sys.path.insert(1, os.path.join(os.path.dirname(sys.path[0]), "lib"))

from errors import SSHErrorRegexList, PythonErrorRegexList
from script import MercurialScript



# MultiLocaleRepack {{{1
class MultiLocaleRepack(MercurialScript):
    config_options = [[
     ["--locale",],
     {"action": "extend",
      "dest": "locales",
      "type": "string",
      "help": "Specify the locale(s) to repack"
     }
    ],[
     ["--merge-locales",],
     {"action": "store_true",
      "dest": "merge_locales",
      "default": False,
      "help": "Use default [en-US] if there are missing strings"
     }
    ],[
     ["--no-merge-locales",],
     {"action": "store_false",
      "dest": "merge_locales",
      "help": "Do not allow missing strings"
     }
    ],[
     ["--en-us-binary-url",],
     {"action": "store",
      "dest": "en_us_binary_url",
      "type": "string",
      "help": "Specify the en-US binary url"
     }
    ],[
     ["--mozilla-repo",],
     {"action": "store",
      "dest": "hg_mozilla_repo",
      "type": "string",
      "help": "Specify the Mozilla repo"
     }
    ],[
     ["--mozilla-tag",],
     {"action": "store",
      "dest": "hg_mozilla_tag",
      "type": "string",
      "help": "Specify the Mozilla tag"
     }
    ],[
     ["--mozilla-dir",],
     {"action": "store",
      "dest": "mozilla_dir",
      "type": "string",
      "default": "mozilla",
      "help": "Specify the Mozilla dir name"
     }
    ],[
     ["--objdir",],
     {"action": "store",
      "dest": "objdir",
      "type": "string",
      "default": "objdir",
      "help": "Specify the objdir"
     }
    ],[
     ["--l10n-base",],
     {"action": "store",
      "dest": "hg_l10n_base",
      "type": "string",
      "help": "Specify the L10n repo base directory"
     }
    ],[
     ["--l10n-tag",],
     {"action": "store",
      "dest": "hg_l10n_tag",
      "type": "string",
      "help": "Specify the L10n tag"
     }
    ],[
     ["--l10n-dir",],
     {"action": "store",
      "dest": "l10n_dir",
      "type": "string",
      "default": "l10n",
      "help": "Specify the l10n dir name"
     }
    ],[
     ["--compare-locales-repo",],
     {"action": "store",
      "dest": "hg_compare_locales_repo",
      "type": "string",
      "help": "Specify the compare-locales repo"
     }
    ],[
     ["--compare-locales-tag",],
     {"action": "store",
      "dest": "hg_compare_locales_tag",
      "type": "string",
      "help": "Specify the compare-locales tag"
     }
    ]]

    def __init__(self, require_config_file=True):
        MercurialScript.__init__(self, config_options=self.config_options,
                                 all_actions=['clobber', 'pull',
                                              'pull-locales',
                                              'setup', 'repack', 'upload'],
                                 require_config_file=require_config_file)
        self.locales = None

    def run(self):
        self.clobber()
        self.pull()
        self.setup()
        self.repack()
        self.upload()
        self.summary()

    def clobber(self):
        if not self.queryAction('clobber'):
            self.info("Skipping clobber step.")
            return
        self.info("Clobbering.")
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        path = os.path.join(base_work_dir, work_dir)
        if os.path.exists(path):
            self.rmtree(path, errorLevel='fatal')

    def queryLocales(self):
        if self.locales:
            return self.locales
        locales = self.queryVar("locales")
        ignore_locales = self.queryVar("ignore_locales")
        if not locales:
            locales = []
            base_work_dir = self.queryVar("base_work_dir")
            work_dir = self.queryVar("work_dir")
            locales_file = os.path.join(base_work_dir, work_dir,
              self.queryVar("locales_file"))
            if locales_file.endswith(".json"):
                locales_json = self.parseConfigFile(locales_file)
                locales = locales_json.keys()
            else:
                fh = open(locales_file)
                locales = fh.read().split()
                fh.close()
            self.debug("Found the locales %s in %s." % (locales, locales_file))
        if ignore_locales:
            for locale in ignore_locales:
                if locale in locales:
                    self.debug("Ignoring locale %s." % locale)
                    locales.remove(locale)
        if locales:
            self.locales = locales
            return self.locales

    def pull(self, repos=None):
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        hg_l10n_base = self.queryVar("hg_l10n_base")
        hg_l10n_tag = self.queryVar("hg_l10n_tag")
        l10n_dir = self.queryVar("l10n_dir")
        if not repos:
            hg_mozilla_repo = self.queryVar("hg_mozilla_repo")
            hg_mozilla_tag = self.queryVar("hg_mozilla_tag")
            mozilla_dir = self.queryVar("mozilla_dir")
            hg_compare_locales_repo = self.queryVar("hg_compare_locales_repo")
            hg_compare_locales_tag = self.queryVar("hg_compare_locales_tag")
            hg_configs_repo = self.queryVar("hg_configs_repo")
            hg_configs_tag = self.queryVar("hg_configs_tag")
            repos = [{
                'repo': hg_mozilla_repo,
                'tag': hg_mozilla_tag,
                'dir_name': mozilla_dir,
            },{
                'repo': hg_compare_locales_repo,
                'tag': hg_compare_locales_tag,
                'dir_name': 'compare-locales',
            },{
                'repo': hg_configs_repo,
                'tag': hg_configs_tag,
                'dir_name': 'configs',
            }]

        # Chicken/egg: need to pull repos to determine locales.
        # Solve by pulling non-locale repos first.
        if not self.queryAction('pull'):
            self.info("Skipping pull step.")
        else:
            self.info("Pulling.")
            self.mkdir_p(abs_work_dir)
            for repo_dict in repos:
                self.scmCheckout(
                 hg_repo=repo_dict['repo'],
                 tag=repo_dict.get('tag', 'default'),
                 dir_name=repo_dict.get('dir_name', None),
                 parent_dir=abs_work_dir
                )

        if not self.queryAction('pull-locales'):
            self.info("Skipping pull locales step.")
        else:
            self.info("Pulling locales.")
            abs_l10n_dir = os.path.join(abs_work_dir, l10n_dir)
            self.mkdir_p(abs_l10n_dir)
            locales = self.queryLocales()
            for locale in locales:
                self.scmCheckout(
                 hg_repo=os.path.join(hg_l10n_base, locale),
                 tag=hg_l10n_tag,
                 parent_dir=abs_l10n_dir
                )

    def setup(self, check_action=True):
        if check_action:
            # We haven't been called from a child object.
            if not self.queryAction("setup"):
                self.info("Skipping setup step.")
                return
            self.info("Setting up.")
        work_dir = self.queryVar("work_dir")
        base_work_dir = self.queryVar("base_work_dir")
        mozconfig = self.queryVar("mozconfig")
        locales_dir = self.queryVar("locales_dir")
        en_us_binary_url = self.queryVar("en_us_binary_url")
        mozilla_dir = self.queryVar("mozilla_dir")
        branding_dir = self.queryVar("branding_dir")
        objdir = self.queryVar("objdir")
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        abs_objdir = os.path.join(abs_work_dir, mozilla_dir, objdir)
        abs_locales_dir = os.path.join(abs_objdir, locales_dir)
        abs_branding_dir = os.path.join(abs_objdir, branding_dir)

        self.chdir(abs_work_dir)
        self.copyfile(mozconfig, os.path.join(mozilla_dir, ".mozconfig"))

        self.rmtree(os.path.join(abs_work_dir, mozilla_dir, objdir, "dist"))

        # TODO error checking
        command = "make -f client.mk configure"
        self._processCommand(command=command, cwd=os.path.join(abs_work_dir, mozilla_dir))
        command = "make"
        self._processCommand(command=command, cwd=os.path.join(abs_objdir, "config"))
        command = "make wget-en-US EN_US_BINARY_URL=%s" % en_us_binary_url
        self._processCommand(command=command, cwd=abs_locales_dir)

        self._getInstaller()
        command = "make unpack"
        self._processCommand(command=command, cwd=abs_locales_dir)
        self._updateRevisions()
        command = "make"
        self._processCommand(command=command, cwd=abs_branding_dir)

    def _getInstaller(self):
        # TODO
        pass

    def _updateRevisions(self):
        # TODO
        pass

    def repack(self):
        if not self.queryAction("repack"):
            self.info("Skipping repack step.")
            return
        self.info("Repacking.")
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        locales_dir = self.queryVar("locales_dir")
        mozilla_dir = self.queryVar("mozilla_dir")
        objdir = self.queryVar("objdir")
        l10n_dir = self.queryVar("l10n_dir")
        merge_locales = self.queryVar("merge_locales")
        merge_dir = "merged"
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        abs_locales_dir = os.path.join(abs_work_dir, mozilla_dir, objdir, locales_dir)
        abs_locales_src_dir = os.path.join(abs_work_dir, mozilla_dir, locales_dir)
        abs_merge_dir = os.path.join(abs_locales_dir, merge_dir)
        locales = self.queryLocales()
        compare_locales_script = os.path.join("..", "..", "..",
                                              "compare-locales",
                                              "scripts", "compare-locales")
        compare_locales_env = os.environ.copy()
        compare_locales_env['PYTHONPATH'] = os.path.join('..', '..', '..',
                                                         'compare-locales', 'lib')
        compare_locales_error_regex_list = list(PythonErrorRegexList)

        for locale in locales:
            self.rmtree(os.path.join(abs_locales_dir, merge_dir))
            # TODO more error checking
            command = "python %s -m %s l10n.ini %s %s" % (
              compare_locales_script, abs_merge_dir,
              os.path.join('..', '..', '..', l10n_dir), locale)
            self.runCommand(command, error_regex_list=compare_locales_error_regex_list,
                            cwd=abs_locales_src_dir, env=compare_locales_env)
            for step in ("chrome", "libs"):
                command = 'make %s-%s L10NBASEDIR=../../../../%s' % (step, locale, l10n_dir)
                if merge_locales:
                    command += " LOCALE_MERGEDIR=%s" % os.path.join(abs_locales_dir, merge_dir)
                self._processCommand(command=command, cwd=abs_locales_dir)
        self._repackage()

    def _repackage(self):
        # TODO
        pass

    def upload(self):
        if not self.queryAction("upload"):
            self.info("Skipping upload step.")
            return
        self.info("Uploading.")

    def _processCommand(self, **kwargs):
        return self.runCommand(**kwargs)

# MaemoMultiLocaleRepack {{{1
class MaemoMultiLocaleRepack(MultiLocaleRepack):
    config_options = MultiLocaleRepack.config_options + [[
     ["--deb-name",],
     {"action": "store",
      "dest": "deb_name",
      "type": "string",
      "help": "Specify the name of the deb"
     }
    ],[
     ["--sbox-target",],
     {"action": "store",
      "dest": "sbox_target",
      "type": "choice",
      "choices": ["FREMANTLE_ARMEL", "CHINOOK-ARMEL-2007"],
      "default": "FREMANTLE_ARMEL",
      "help": "Specify the scratchbox target"
     }
    ],[
     ["--sbox-ome",],
     {"action": "store",
      "dest": "sbox_home",
      "type": "string",
      "default": "/scratchbox/users/cltbld/home/cltbld/",
      "help": "Specify the scratchbox user home directory"
     }
    ],[
     ["--sbox-root",],
     {"action": "store",
      "dest": "sbox_root",
      "type": "string",
      "default": "/scratchbox/users/cltbld",
      "help": "Specify the scratchbox user home directory"
     }
    ],[
     ["--sbox_path",],
     {"action": "store",
      "dest": "sbox_path",
      "type": "string",
      "default": "/scratchbox/moz_scratchbox",
      "help": "Specify the scratchbox executable"
     }
    ],[
     ["--mobile-repo",],
     {"action": "store",
      "dest": "hg_mobile_repo",
      "type": "string",
      "help": "Specify the mobile repo"
     }
    ],[
     ["--mobile-tag",],
     {"action": "store",
      "dest": "hg_mobile_tag",
      "type": "string",
      "help": "Specify the mobile tag"
     }
    ]]

    def __init__(self, **kwargs):
        MultiLocaleRepack.__init__(self, **kwargs)
        self.deb_name = None
        self.deb_package_version = None

    def pull(self):
        hg_mozilla_repo = self.queryVar("hg_mozilla_repo")
        hg_mozilla_tag = self.queryVar("hg_mozilla_tag")
        mozilla_dir = self.queryVar("mozilla_dir")
        hg_compare_locales_repo = self.queryVar("hg_compare_locales_repo")
        hg_compare_locales_tag = self.queryVar("hg_compare_locales_tag")
        hg_mobile_repo = self.queryVar("hg_mobile_repo")
        hg_mobile_tag = self.queryVar("hg_mobile_tag")
        hg_configs_repo = self.queryVar("hg_configs_repo")
        hg_configs_tag = self.queryVar("hg_configs_tag")
        repos = [{
            'repo': hg_mozilla_repo,
            'tag': hg_mozilla_tag,
            'dir_name': mozilla_dir,
        },{
            'repo': hg_mobile_repo,
            'tag': hg_mobile_tag,
            'dir_name': os.path.join(mozilla_dir, 'mobile'),
        },{
            'repo': hg_compare_locales_repo,
            'tag': hg_compare_locales_tag,
            'dir_name': 'compare-locales',
        },{
            'repo': hg_configs_repo,
            'tag': hg_configs_tag,
            'dir_name': 'configs',
        }]
        MultiLocaleRepack.pull(self, repos=repos)

    def setup(self):
        if not self.queryAction("setup"):
            self.info("Skipping setup step.")
            return
        self.info("Setting up.")
        sbox_path = self.queryVar("sbox_path")
        sbox_target = self.queryVar("sbox_target")
        self.runCommand("%s -p sb-conf select %s" % (sbox_path, sbox_target))
        self.runCommand("%s -p \"echo -n TinderboxPrint: && sb-conf current | sed 's/ARMEL// ; s/_// ; s/-//'\"" % sbox_path)
        MultiLocaleRepack.setup(self, check_action=False)

    def queryDebName(self):
        if self.deb_name:
            return self.deb_name
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        mozilla_dir = self.queryVar("mozilla_dir")
        objdir = self.queryVar("objdir")
        locales_dir = self.queryVar("locales_dir")
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        abs_locales_dir = os.path.join(abs_work_dir, mozilla_dir, objdir, locales_dir)
        en_us_binary_url = self.queryVar("en_us_binary_url")

        command = "make wget-DEB_PKG_NAME EN_US_BINARY_URL=%s" % en_us_binary_url
        self.deb_name = self._processCommand(command=command, cwd=abs_locales_dir,
                                            halt_on_failure=True,
                                            return_type='output')
        return self.deb_name

    def queryDebPackageVersion(self):
        if self.deb_package_version:
            return self.deb_package_version
        deb_name = self.queryDebName()
        m = re.match(r'[^_]+_([^_]+)_', deb_name)
        self.deb_package_version = m.groups()[0]
        return self.deb_package_version

    def _getInstaller(self):
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        mozilla_dir = self.queryVar("mozilla_dir")
        objdir = self.queryVar("objdir")
        locales_dir = self.queryVar("locales_dir")
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        abs_locales_dir = os.path.join(abs_work_dir, mozilla_dir, objdir, locales_dir)
        en_us_binary_url = self.queryVar("en_us_binary_url")

        deb_name = self.queryDebName()

        command = "make wget-deb EN_US_BINARY_URL=%s DEB_PKG_NAME=%s DEB_BUILD_ARCH=armel" % (en_us_binary_url, deb_name)
        self._processCommand(command=command, cwd=abs_locales_dir)

    def _updateRevisions(self):
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        locales_dir = self.queryVar("locales_dir")
        objdir = self.queryVar("objdir")
        mozilla_dir = self.queryVar("mozilla_dir")
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        abs_locales_dir = os.path.join(abs_work_dir, mozilla_dir, objdir, locales_dir)

        command = "make ident"
        output = self._processCommand(command=command, cwd=abs_locales_dir,
                                      return_type='output')
        for line in output.split('\n'):
            if line.startswith('gecko_revision '):
                gecko_revision = line.split(' ')[-1]
            elif line.startswith('fennec_revision '):
                fennec_revision = line.split(' ')[-1]
        self.scmUpdate(os.path.join(abs_work_dir, mozilla_dir),
                       tag=gecko_revision)
        self.scmUpdate(os.path.join(abs_work_dir, mozilla_dir, "mobile"),
                       tag=fennec_revision)

    def _repackage(self):
        base_work_dir = self.queryVar("base_work_dir")
        work_dir = self.queryVar("work_dir")
        mozilla_dir = self.queryVar("mozilla_dir")
        objdir = self.queryVar("objdir")
        abs_work_dir = os.path.join(base_work_dir, work_dir)
        abs_objdir = os.path.join(abs_work_dir, mozilla_dir, objdir)
        deb_name = self.queryDebName()
        deb_package_version = self.queryDebPackageVersion()
        tmp_deb_dir = os.path.join("dist", "tmp.deb")
        abs_tmp_deb_dir = os.path.join(abs_objdir, tmp_deb_dir)

        # TODO error checking
#        command = "make package AB_CD=multi"
#        self._processCommand(command=command, cwd=abs_objdir)
        command = "make deb AB_CD=multi DEB_PKG_NAME=%s DEB_PKG_VERSION=%s" % (deb_name, deb_package_version)
        self._processCommand(command=command, cwd=abs_objdir)

        self.rmtree(os.path.join(abs_tmp_deb_dir))
        self.mkdir_p(os.path.join(abs_tmp_deb_dir, "DEBIAN"))
        ar_error_regex_list = [{
         'substr': 'No such file or directory', 'level': 'error'
        },{
         'substr': 'Cannot write: Broken pipe', 'level': 'error'
        }]
        command = "ar p mobile/locales/%s control.tar.gz | tar zxv -C %s/DEBIAN" % \
          (deb_name, tmp_deb_dir)
        self.runCommand(command=command, cwd=abs_objdir,
                        error_regex_list=ar_error_regex_list)
        command = "ar p mobile/locales/%s data.tar.gz | tar zxv -C %s" % \
          (deb_name, tmp_deb_dir)
        self.runCommand(command=command, cwd=abs_objdir,
                        error_regex_list=ar_error_regex_list)
        command = "ar p mobile/%s data.tar.gz | tar zxv -C %s" % \
          (deb_name, tmp_deb_dir)
        self.runCommand(command=command, cwd=abs_objdir,
                        error_regex_list=ar_error_regex_list)

        # fix DEBIAN/md5sums
        self.info("Creating md5sums file...")
        command = "find * -type f | grep -v DEBIAN"
        file_list = self.getOutputFromCommand(command=command, cwd=abs_tmp_deb_dir).split('\n')
        md5_file = os.path.join(abs_tmp_deb_dir, "DEBIAN", "md5sums")
        md5_fh = open(md5_file, 'w')
        for file_name in file_list:
            contents = open(os.path.join(abs_tmp_deb_dir, file_name)).read()
            md5sum = hashlib.md5(contents).hexdigest()
            md5_fh.write("%s  %s\n" % (md5sum, file_name))
        md5_fh.close()

        command = "dpkg-deb -b %s dist/%s" % (abs_tmp_deb_dir, deb_name)
        self._processCommand(command=command, cwd=abs_objdir)

    def _processCommand(self, **kwargs):
        sbox_path = self.queryVar("sbox_path")
        sbox_home = self.queryVar("sbox_home")
        sbox_root = self.queryVar("sbox_root")
        command = '%s ' % sbox_path
        if 'return_type' not in kwargs or kwargs['return_type'] != 'output':
            command += '-p '
        if 'cwd' in kwargs:
            command += '-d %s ' % kwargs['cwd'].replace(sbox_home, '')
            del kwargs['cwd']
        kwargs['command'] = '%s "%s"' % (command, kwargs['command'].replace(sbox_root, ''))
        if 'return_type' not in kwargs or kwargs['return_type'] != 'output':
            if 'error_regex_list' in kwargs:
                kwargs['error_regex_list'] = PythonErrorRegexList + kwargs['error_regex_list']
            else:
                kwargs['error_regex_list'] = PythonErrorRegexList
            return self.runCommand(**kwargs)
        else:
            del(kwargs['return_type'])
            return self.getOutputFromCommand(**kwargs)



# __main__ {{{1
if __name__ == '__main__':
    maemoRepack = MaemoMultiLocaleRepack()
    maemoRepack.run()