#
# Cookbook:: calusari
# Recipe:: caddy
#
# Copyright:: 2018, The Authors, All Rights Reserved.

caddy_path = '/usr/local/bin'
caddy_bin = '/usr/local/bin/caddy'

group 'www-data' do
  gid 33
end

user 'www-data' do
  uid 33
  gid 33
  system true
  home '/soft/calusari'
  manage_home false
  shell '/usr/sbin/nologin'
end

group 'ssl-cert' do
  system true
  members 'www-data'
  append true
end

tar_extract 'caddy.tar.gz'  do
  source 'https://caddyserver.com/download/linux/amd64?license=personal&telemetry=off'
  target_dir caddy_path
  creates caddy_bin
  checksum '5e701b6ea4df276dc2814e082b47d633c311637b02baae96feba0c7f0169d556'
  tar_flags '-po caddy'
  notifies :restart, 'service[caddy]'
end

execute "setcap 'cap_net_bind_service=+ep' #{caddy_bin}" do
  action :nothing
  subscribes :run, 'tar_extract[caddy.tar.gz]', :immediately
end

directory '/etc/caddy' do
  owner 'root'
  group 'root'
  action :create
end

template '/etc/caddy/Caddyfile' do
  source 'Caddyfile.erb'
  mode '644'
end

directory '/etc/ssl/caddy' do
  owner 'root'
  group 'www-data'
  mode '770'
end

directory '/soft/calusari' do
  owner 'www-data'
  group 'www-data'
  mode '555'
  recursive true
  action :create
end

# systemd_unit 'caddy.service' do
#   triggers_reload true
#   content(
#     Unit: {
#       Description: 'Caddy HTTP/2 web server',
#       Documentation: 'https://caddyserver.com/docs',
#       After: 'network-online.target',
#       Wants: 'network-online.target systemd-networkd-wait-online.service'
#     },
#     Service: {
#       Restart: 'on-abnormal',
#       User: 'www-data',
#       Group: 'www-data',
#       Environment: 'CADDYPATH=/etc/ssl/caddy',
#       ExecStart: '/usr/local/bin/caddy -log stdout -agree=true -conf=/etc/caddy/Caddyfile -root=/var/tmp',
#       ExecReload: '/bin/kill -USR1 $MAINPID',
#       KillMode: 'mixed',
#       KillSignal: 'SIGQUIT',
#       TimeoutStopSec: '5s'
#     },
#     Install: {
#       WantedBy: 'multi-user.target'
#     }
#   )
# end

systemd = template '/etc/systemd/system/caddy.service' do
  source 'caddy.service.erb'
  mode '644'
  only_if { node['platform'] == 'ubuntu' && node['platform_version'] >= '15.04' }
end

service 'caddy' do
  action [:enable, :start]
  supports :status => true, :start => true, :stop => true, :restart => true
  subscribes :restart, systemd, :immediately
end
