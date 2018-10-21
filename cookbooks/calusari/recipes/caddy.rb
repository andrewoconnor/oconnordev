#
# Cookbook:: calusari
# Recipe:: caddy
#
# Copyright:: 2018, The Authors, All Rights Reserved.

caddy_path = '/usr/local/bin'
caddy_bin = '/usr/local/bin/caddy'

tar_extract 'caddy'  do
  source 'https://caddyserver.com/download/linux/amd64?license=personal&telemetry=off'
  target_dir caddy_path
  creates caddy_bin
  checksum 'ecb80d18bca47c1922c8395a8e018a0b5f63285f288bd9e11ceae9b66e02b464'
  notifies :restart, 'service[caddy]'
end

execute "setcap cap_net_bind_service=+ep caddy" do
  cwd caddy_path
  action :nothing
  subscribes :run, 'tar_extract[caddy]', :immediately
end

systemd = template '/etc/systemd/system/caddy.service' do
  source 'caddy.service.erb'
  mode '0755'
  only_if { node['platform'] == 'ubuntu' && node['platform_version'] >= '15.04' }
end

service 'caddy' do
  action [:enable, :start]
  supports :status => true, :start => true, :stop => true, :restart => true
  subscribes :restart, systemd, :immediately
end
