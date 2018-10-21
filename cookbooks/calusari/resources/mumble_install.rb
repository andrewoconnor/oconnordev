#
# Cookbook:: calusari
# Resource:: mumble_install
#
# Copyright:: 2018, The Authors, All Rights Reserved.

property :welcome_text, String, default: '"<br />Welcome to this server running <b>Murmur</b>.<br />Enjoy your stay!<br />"'
property :server_password, String, default: ''
property :bandwidth, Integer, default: 72000
property :users, Integer, default: 100
property :opus_threshold, Integer, default: 100
property :register_name, String, default: 'Mumble Server'
property :ssl_cert, String
property :ssl_key, String
property :ssl_ca, String

action :install do
  apt_repository 'mumble' do
    uri 'ppa:mumble/snapshot'
    keyserver 'keyserver.ubuntu.com'
    key '7F05CF9E'
  end

  apt_package 'mumble-server' do
    action :install
  end

  template '/etc/mumble-server.ini' do
    source 'murmur.ini.erb'
    variables(
      welcome_text: new_resource.welcome_text,
      server_password: new_resource.server_password,
      bandwidth: new_resource.bandwidth,
      users: new_resource.users,
      opus_threshold: new_resource.opus_threshold,
      register_name: new_resource.register_name,
      ssl_cert: new_resource.ssl_cert,
      ssl_key: new_resource.ssl_key,
      ssl_ca: new_resource.ssl_ca
    )
    notifies :restart, 'service[mumble-server]'
  end
end
