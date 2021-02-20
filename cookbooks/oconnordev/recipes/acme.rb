#
# Cookbook:: oconnordev
# Recipe:: acme
#
# Copyright:: 2018, The Authors, All Rights Reserved.

# Include the recipe to install the gems

include_recipe 'acme'

# node.rm('acme', 'private_key')

node.override['acme']['contact'] = ['mailto:andrewoconnor@outlook.com']
node.override['acme']['endpoint'] = 'https://acme-v01.api.letsencrypt.org'

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
end

file "/etc/ssl/local_certs/private/#{site}.key" do
  mode '440'
end

# Set up your webserver here...

# Get and auto-renew the certificate from Let's Encrypt
acme_certificate site do
  crt        "/etc/ssl/local_certs/#{site}.crt"
  key        "/etc/ssl/local_certs/private/#{site}.key"
  chain      "/etc/ssl/local_certs/#{site}.pem"
  wwwroot    node['acme']['wwwroot']
  alt_names  sans
end
