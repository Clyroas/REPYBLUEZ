#!/usr/bin/env python3
"""Build script for PyBluez.

Static project metadata lives in pyproject.toml; this file only contains the
platform-dependent parts: the C extension modules, package layout, and the
macOS-specific build steps for the LightAquaBlue framework.
"""
import os
import sys

from setuptools import setup, Extension


# This marks the wheel as always being platform-specific and not pure Python
# See: https://stackoverflow.com/q/45150304/145504
try:
    from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel
except ImportError:
    try:
        from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
    except ImportError:
        _bdist_wheel = None

if _bdist_wheel is not None:
    class impure_bdist_wheel(_bdist_wheel):
        def finalize_options(self):
            _bdist_wheel.finalize_options(self)
            self.root_is_pure = False


packages = ['bluetooth']
package_dir = dict()
ext_modules = list()
install_requires = list()
package_data = dict()
eager_resources = list()
zip_safe = True


if sys.platform == 'win32':
    ext_modules.append(Extension('bluetooth._msbt',
                       libraries=["WS2_32", "Bthprops"],
                       sources=['msbt\\_msbt.c']))

elif sys.platform.startswith('linux'):
    mod1 = Extension('bluetooth._bluetooth',
                     libraries = ['bluetooth'],
                     #extra_compile_args=['-O0'],
                     sources = ['bluez/btmodule.c', 'bluez/btsdp.c'])
    ext_modules.append(mod1)

elif sys.platform.startswith("darwin"):
    packages.append('lightblue')
    package_dir['lightblue'] = 'macos'
    zip_safe = False

    install_requires += ['pyobjc-core>=6', 'pyobjc-framework-Cocoa>=6']

    # FIXME: This is inelegant, how can we cover the cases?
    build_cmds = {'bdist', 'bdist_egg', 'bdist_wheel'}
    if build_cmds & set(sys.argv):
        # Build the framework into macos/
        import subprocess
        subprocess.check_call([
            'xcodebuild', 'install',
            '-project', 'macos/LightAquaBlue/LightAquaBlue.xcodeproj',
            '-scheme', 'LightAquaBlue',
            'DSTROOT=' + os.path.join(os.getcwd(), 'macos'),
            'INSTALL_PATH=/',
            'DEPLOYMENT_LOCATION=YES',
        ])
        
        # We can't seem to list a directory as package_data, so we will
        # recursively add all all files we find
        package_data['lightblue'] = []
        for path, _, files in os.walk('macos/LightAquaBlue.framework'):
            for f in files:
                include = os.path.join(path, f)[6:]  # trim off macos/
                package_data['lightblue'].append(include)
    
        # This should allow us to use the framework from an egg [untested]
        eager_resources.append('macos/LightAquaBlue.framework')
        
else:
    raise Exception("This platform (%s) is currently not supported by pybluez."
                    % sys.platform)


setup_args = dict(
    ext_modules=ext_modules,
    packages=packages,
    package_dir=package_dir,
    install_requires=install_requires,
    package_data=package_data,
    eager_resources=eager_resources,
    zip_safe=zip_safe,
)

if _bdist_wheel is not None:
    setup_args['cmdclass'] = {'bdist_wheel': impure_bdist_wheel}

setup(**setup_args)
