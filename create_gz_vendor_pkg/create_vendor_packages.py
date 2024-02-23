import argparse
import sys
from catkin_pkg.package import Dependency, parse_package_string, Package
import re
import copy
import jinja2
from pathlib import Path


GZ_LIBRARIES = [
    'gz-cmake',
    'gz-common',
    'gz-fuel-tools',
    'gz-gui',
    'gz-launch',
    'gz-math',
    'gz-msgs',
    'gz-physics',
    'gz-plugin',
    'gz-rendering',
    'gz-sensors',
    'gz-sim',
    'gz-tools',
    'gz-transport',
    'gz-utils',
    'sdformat',
]

def remove_version(pkg_name: str):
    pkg_name_no_version = re.match('[-_a-z]*', pkg_name)
    if not pkg_name_no_version:
        raise RuntimeError("Could not parse package name")
    return pkg_name_no_version.group(0)

def create_vendor_name(pkg_name: str):
    return f"{pkg_name.replace('-', '_')}_vendor"

def is_gz_library(dep: Dependency):
    pkg_name_no_version = remove_version(dep.name)
    return pkg_name_no_version in GZ_LIBRARIES

def vendorize_gz_dependency(dep: Dependency):
    pkg_name_no_version = remove_version(dep.name)
    dep.name = create_vendor_name(pkg_name_no_version) 

def separate_gz_deps(deps):
    gz_deps = []
    non_gz_deps = []
    for dep in deps:
        if is_gz_library(dep):
            gz_deps.append(dep)
        else:
            non_gz_deps.append(dep)
    return gz_deps, non_gz_deps

def split_version(version: str):
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)$', version)
    if match is None:
        raise ValueError(f'Invalid version string, must be int.int.int: "{version}"')
    new_version = match.groups()
    new_version = [int(x) for x in new_version]
    return {'major': new_version[0], 'minor': new_version[1], 'patch': new_version[2]}

def get_lib_designator(pkg_name: str):
    gz_match = re.match(r'gz-(.*)', pkg_name)
    if gz_match:
        return gz_match.group(1)
    elif pkg_name == 'sdformat':
        return 'sdformat'
    else:
        raise ValueError(f'Could not extract designator from pkg_name: "{pkg_name}"')

def stable_unique(items: list):
    unique_items = []
    for item in items:
        if item not in unique_items:
            unique_items.append(item)
    return unique_items

def create_vendor_package_xml(src_pkg_xml: Package):
    templates_path = Path(__file__).resolve().parent / "templates"
    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(templates_path),
                                   trim_blocks=True, lstrip_blocks=True)
    template = jinja_env.get_template("package.xml.jinja")
    vendor_pkg_xml = copy.deepcopy(src_pkg_xml)

    pkg_name_no_version = remove_version(vendor_pkg_xml.name)
    vendor_name = create_vendor_name(pkg_name_no_version)

    # The gazebo dependencies need to be vendored and we need to use `<depend>`
    # on each dependency regardless of whether it's a build or exec dependency
    gz_build_deps, vendor_pkg_xml.build_depends = separate_gz_deps(vendor_pkg_xml.build_depends)
    gz_exec_deps, vendor_pkg_xml.exec_depends = separate_gz_deps(vendor_pkg_xml.exec_depends)
    gz_test_deps, vendor_pkg_xml.test_depends = separate_gz_deps(vendor_pkg_xml.test_depends)
    gz_doc_deps, vendor_pkg_xml.doc_depends = separate_gz_deps(vendor_pkg_xml.doc_depends)

    gz_deps = stable_unique(gz_build_deps + gz_exec_deps + gz_test_deps + gz_doc_deps)

    for dep in gz_deps:
        vendorize_gz_dependency(dep)

    return template.render(pkg=vendor_pkg_xml, vendor_name=vendor_name, gz_vendor_deps=gz_deps)

def create_cmake_file(src_pkg_xml: Package):
    templates_path = Path(__file__).resolve().parent / "templates"
    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(templates_path),
                                   trim_blocks=True, lstrip_blocks=True)
    template = jinja_env.get_template("CMakeLists.txt.jinja")
    vendor_pkg_xml = copy.deepcopy(src_pkg_xml)

    pkg_name_no_version = remove_version(vendor_pkg_xml.name)
    vendor_name = create_vendor_name(pkg_name_no_version)

    # The gazebo dependencies need to be vendored and we need to use `<depend>`
    # on each dependency regardless of whether it's a build or exec dependency
    gz_build_deps, _ = separate_gz_deps(vendor_pkg_xml.build_depends)
    gz_exec_deps, _ = separate_gz_deps(vendor_pkg_xml.exec_depends)
    gz_test_deps, _ = separate_gz_deps(vendor_pkg_xml.test_depends)
    gz_doc_deps, _ = separate_gz_deps(vendor_pkg_xml.doc_depends)

    gz_deps = stable_unique(gz_build_deps + gz_exec_deps + gz_test_deps + gz_doc_deps)

    for dep in gz_deps:
        vendorize_gz_dependency(dep)

    # gz-fuel-tools needs special care as it's cmake package name is different
    # from its deb package name.
    cmake_pkg_name = pkg_name_no_version
    if cmake_pkg_name == 'gz-fuel-tools':
        cmake_pkg_name = 'gz-fuel_tools'

    has_extra_cmake = pkg_name_no_version in ['gz-tools', 'gz-cmake']

    return template.render(pkg=vendor_pkg_xml, cmake_pkg_name=cmake_pkg_name,
                           github_pkg_name=pkg_name_no_version,
                           vendor_name=vendor_name, gz_vendor_deps=gz_deps,
                           has_extra_cmake=has_extra_cmake,
                           version=split_version(vendor_pkg_xml.version))

def generate_vendor_package_files(package: Package, output_dir):
    output_package_xml = create_vendor_package_xml(package)
    output_cmake = create_cmake_file(package)
    if output_dir :
        with open(Path(output_dir) / "package.xml", 'w') as f:
            f.write(output_package_xml)
        with open(Path(output_dir) / "CMakeLists.txt", 'w') as f:
            f.write(output_cmake)
    else:
        print(output_package_xml)
        print(output_cmake)

def main(argv=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        description='Parse package.xml file and generate a vendor package',
    )
    parser.add_argument(
        '--output_dir',
        type=str,
        help='Output directory',
    )
    parser.add_argument(
        'input_package_xml',
        type=argparse.FileType('r', encoding='utf-8'),
        help='The path to a package.xml file',
    )
    args = parser.parse_args(argv)
    try:
        package = parse_package_string(
            args.input_package_xml.read(), filename=args.input_package_xml.name)
    except Exception as e:
        print("Error parsing '%s':" % args.input_package_xml.name, file=sys.stderr)
        raise e
    finally:
        args.input_package_xml.close()

    generate_vendor_package_files(package, args.output_dir)


if __name__ == "__main__":
    main()