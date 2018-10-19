#
# Cookbook:: calusari
# Recipe:: mumble-server
#
# Copyright:: 2018, The Authors, All Rights Reserved.

service 'mumble-server' do
  supports :start => true, :stop => true, :restart => true, :status => true
  action [:enable, :start]
end

calusari_mumble_install 'mumble-server' do
  welcometext node['mumble-server']['welcometext']
  serverpassword data_bag_item('passwords', 'mumble-server')['serverpassword']
  bandwidth node['mumble-server']['bandwidth']
  users node['mumble-server']['users']
  opusthreshold node['mumble-server']['opusthreshold']
  root_channel_name node['mumble-server']['root_channel_name']
  action :install
end
