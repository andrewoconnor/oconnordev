#
# Cookbook:: calusari
# Attributes:: default
#
# Copyright:: 2018, The Authors, All Rights Reserved.

default['murmur']['welcome_text'] = '"<br />Welcome to this server running <b>Murmur</b>.<br />Enjoy your stay!<br />"'
default['murmur']['server_password'] = ''
default['murmur']['bandwidth'] = 72000
default['murmur']['users'] = 100
default['murmur']['opus_threshold'] = 100
default['murmur']['register_name'] = 'Mumble Server'

default['caddy']['download_url'] = 'https://caddyserver.com/download/linux/amd64?license=personal&telemetry=off'
default['caddy']['checksum'] = ''
