#
# Cookbook:: apache
# Recipe:: caddy
#
# Copyright:: 2018, The Authors, All Rights Reserved.

apache = %w[
  apache2
  apache2-bin
  apache2-data
  apache2-doc
  apache2-utils
  apache2.2-bin
  apache2.2-common
]

service 'apache2' do
  action :stop
end

package apache do
  action :purge
end
