#
# Cookbook:: oconnordev
# Recipe:: acme
#
# Copyright:: 2018, The Authors, All Rights Reserved.

# Include the recipe to install the gems
include_recipe 'oconnordev::gai'
include_recipe 'oconnordev::caddy'
include_recipe 'oconnordev::murmur'
include_recipe 'acme'

site = node['acme']['site']
sans = node['acme']['sans']

directory '/etc/ssl/local_certs' do
  owner 'root'
  group 'root'
  mode '755'
  action :create
end

directory '/etc/ssl/local_certs/private' do
  owner 'root'
  group 'ssl-cert'
  mode '750'
  action :create
end

# Generate a self-signed if we don't have a cert to prevent bootstrap problems
acme_selfsigned site do
  crt     "/etc/ssl/local_certs/#{site}.crt"
  key     "/etc/ssl/local_certs/private/#{site}.key"
  chain   "/etc/ssl/local_certs/#{site}.pem"
  owner   'root'
  group   'ssl-cert'
  notifies :restart, 'systemd_unit[caddy.service]', :immediate
end

file "/etc/ssl/local_certs/private/#{site}.key" do
  mode '440'
end

# Set up your webserver here...

# Get and auto-renew the certificate from Let's Encrypt
acme_certificate site do
  crt                "/etc/ssl/local_certs/#{site}.crt"
  key                "/etc/ssl/local_certs/private/#{site}.key"
  chain              "/etc/ssl/local_certs/#{site}.pem"
  wwwroot            node['acme']['wwwroot']
  notifies :restart, 'systemd_unit[caddy.service]'
  notifies :restart, 'service[mumble-server]'
  alt_names sans
end
