name 'oconnordev'
maintainer 'Andrew O\'Connor'
maintainer_email 'andrewoconnor@outlook.com'
license ''
description 'Installs/Configures oconnordev'
long_description 'Installs/Configures oconnordev'
version '0.1.0'
chef_version '>= 12.14' if respond_to?(:chef_version)

# The `issues_url` points to the location where issues for this cookbook are
# tracked.  A `View Issues` link will be displayed on this cookbook's page when
# uploaded to a Supermarket.
#
# issues_url 'https://github.com/<insert_org_here>/oconnordev/issues'

# The `source_url` points to the development repository for this cookbook.  A
# `View Source` link will be displayed on this cookbook's page when uploaded to
# a Supermarket.
#
# source_url 'https://github.com/<insert_org_here>/oconnordev'

depends 'acme', '~> 4.1.2'
depends 'getaddrinfo', '~> 0.1.0'
depends 'ruby_rbenv', '~> 2.4.0'
depends 'tar', '~> 2.2.0'
depends 'zipfile', '~> 0.2.0'
