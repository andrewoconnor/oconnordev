#
# Cookbook:: calusari
# Resource:: mumble_install
#
# Copyright:: 2018, The Authors, All Rights Reserved.

property :welcometext, String, default: '"<br />Welcome to this server running <b>Murmur</b>.<br />Enjoy your stay!<br />"'
property :serverpassword, String, default: ''
property :bandwidth, Integer, default: 72000
property :users, Integer, default: 100
property :opusthreshold, Integer, default: 100
property :root_channel_name, String, default: 'Mumble Server'

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
    source 'mumble-server.ini.erb'
    variables(
      welcometext: new_resource.welcometext,
      serverpassword: new_resource.serverpassword,
      bandwidth: new_resource.bandwidth,
      users: new_resource.users,
      opusthreshold: new_resource.opusthreshold,
      registerName: new_resource.root_channel_name
    )
    notifies :restart, 'service[mumble-server]'
  end
end
