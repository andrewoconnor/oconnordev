#
# Cookbook:: oconnordev
# Recipe:: fivem
#
# Copyright:: 2018, The Authors, All Rights Reserved.

apt_package ['git', 'xz-utils'] do
  action :install
end

user 'fivem' do
  system true
  home '/opt/fivem'
  manage_home false
  shell '/usr/sbin/nologin'
end

directory '/opt/fivem' do
  owner 'fivem'
  group 'fivem'
  action :create
end

template '/opt/fivem/screen.conf' do
  source 'screen.conf.erb'
  owner 'fivem'
  group 'fivem'
end

directory '/opt/fivem/server' do
  owner 'fivem'
  group 'fivem'
  action :create
end

tar_extract 'fx.tar.xz' do
  source node['fivem']['download_url']
  target_dir '/opt/fivem/server'
  notifies :run, 'execute[chown-server]'
  notifies :restart, 'systemd_unit[fivem.service]'
end

execute 'chown-server' do
  command 'chown -R fivem:fivem /opt/fivem/server/'
  user 'root'
  action :nothing
end

git '/opt/fivem/server-data' do
  repository 'https://github.com/citizenfx/cfx-server-data.git'
  user 'fivem'
  group 'fivem'
  notifies :restart, 'systemd_unit[fivem.service]'
end

# vMenu

remote_file '/var/chef/cache/vMenu.zip' do
  source node['fivem']['vmenu_url']
  mode '755'
end

zipfile '/var/chef/cache/vMenu.zip' do
  into '/opt/fivem/server-data/resources/vMenu'
  overwrite true
  notifies :run, 'execute[chown-vMenu]'
end

execute 'chown-vMenu' do
  command 'chown -R fivem:fivem /opt/fivem/server-data/resources/vMenu'
  user 'root'
  action :nothing
end

template '/opt/fivem/server-data/permissions.cfg' do
  source 'vMenu.cfg.erb'
  owner 'fivem'
  group 'fivem'
  variables(admin: node['fivem']['admin'])
  notifies :restart, 'systemd_unit[fivem.service]'
end

# FiveM

template '/opt/fivem/server-data/server.cfg' do
  source 'fivem.cfg.erb'
  owner 'fivem'
  group 'fivem'
  variables(
    tags: node['fivem']['tags'],
    hostname: node['fivem']['hostname'],
    admin: node['fivem']['admin'],
    steam_web_api_key: data_bag_item('passwords', 'fivem')['steam_web_api_key'],
    license_key: node['fivem']['license_key']
  )
  notifies :restart, 'systemd_unit[fivem.service]'
end

systemd_unit 'fivem.service' do
  content(
    Unit: {
      Description: 'FiveM FXServer',
      Documentation: 'https://docs.fivem.net',
      After: 'network-online.target',
      Wants: 'network-online.target'
    },
    Service: {
      User: 'fivem',
      Group: 'fivem',
      WorkingDirectory: '/opt/fivem/server-data',
      ExecStart: '/usr/bin/screen -c /opt/fivem/screen.conf -DmS fivem /opt/fivem/server/run.sh "+exec server.cfg"',
      ReadWriteDirectories: '/opt/fivem'
    },
    Install: {
      WantedBy: 'multi-user.target'
    }
  )
  action [:create, :enable, :start]
end
