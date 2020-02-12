#
# Cookbook:: oconnordev
# Recipe:: caddy
#
# Copyright:: 2018, The Authors, All Rights Reserved.

caddy_dir = '/usr/local/bin'
caddy_bin = '/usr/local/bin/caddy'

group 'www-data' do
  gid 33
end

user 'www-data' do
  uid 33
  gid 33
  system true
  home node['caddy']['wwwroot']
  manage_home false
  shell '/usr/sbin/nologin'
end

group 'ssl-cert' do
  system true
  members 'www-data'
  append true
end

remote_file caddy_bin do
  source node['caddy']['download_url']
  mode '755'
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
  variables(
    site: node['caddy']['site'],
    wwwroot: node['caddy']['wwwroot'],
    ssl_cert: node['caddy']['ssl_cert'],
    ssl_key: node['caddy']['ssl_key'] 
  )
  notifies :reload, 'systemd_unit[caddy.service]'
end

directory '/etc/ssl/caddy' do
  owner 'root'
  group 'www-data'
  mode '770'
end

directory node['caddy']['wwwroot'] do
  owner 'www-data'
  group 'www-data'
  mode '555'
  recursive true
  action :create
end

systemd_unit 'caddy.service' do
  triggers_reload true
  content(
    Unit: {
      Description: 'Caddy HTTP/2 web server',
      Documentation: 'https://caddyserver.com/docs',
      After: 'network-online.target',
      Wants: 'network-online.target systemd-networkd-wait-online.service'
    },
    Service: {
      Restart: 'on-abnormal',
      User: 'www-data',
      Group: 'www-data',
      Environment: 'CADDYPATH=/etc/ssl/caddy',
      ExecStart: '/usr/local/bin/caddy run --config /etc/caddy/Caddyfile --adapter caddyfile',
      ExecReload: '/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile',
      ExecStop: '/usr/local/bin/caddy stop',
      KillMode: 'mixed',
      KillSignal: 'SIGQUIT',
      TimeoutStopSec: '5s',
      LimitNOFILE: '1048576',
      LimitNPROC: '512',
      PrivateTmp: 'true',
      PrivateDevices: 'true',
      ProtectHome: 'true',
      ProtectSystem: 'full',
      ReadWriteDirectories: '/etc/ssl/caddy',
      CapabilityBoundingSet: 'CAP_NET_BIND_SERVICE',
      AmbientCapabilities: 'CAP_NET_BIND_SERVICE',
      NoNewPrivileges: 'true'
    },
    Install: {
      WantedBy: 'multi-user.target'
    }
  )
  action [:create, :enable, :start]
  subscribes :reload, "file[#{node['caddy']['ssl_cert']}]", :immediately
end
