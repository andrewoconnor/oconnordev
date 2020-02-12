#
# Cookbook:: oconnordev
# Recipe:: murmur
#
# Copyright:: 2018, The Authors, All Rights Reserved.

oconnordev_mumble_install 'murmur' do
  welcome_text node['murmur']['welcome_text']
  server_password data_bag_item('passwords', 'murmur')['server_password']
  bandwidth node['murmur']['bandwidth']
  users node['murmur']['users']
  opus_threshold node['murmur']['opus_threshold']
  register_name node['murmur']['register_name']
  ssl_cert node['murmur']['ssl_cert']
  ssl_key node['murmur']['ssl_key']
  ssl_ca node['murmur']['ssl_ca']
  action :install
end

# service 'mumble-server' do
#   supports status: true, start: true, stop: true, restart: true
#   action [:enable, :start]
#   subscribes :restart, "file[#{node['murmur']['ssl_cert']}]", :immediately
# end

# systemd_unit 'mumble-server.service' do
#   action [:enable, :start]
#   subscribes :restart, "file[#{node['murmur']['ssl_cert']}]", :immediately
# end
