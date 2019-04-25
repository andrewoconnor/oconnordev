#
# Cookbook:: oconnordev
# Attributes:: default
#
# Copyright:: 2018, The Authors, All Rights Reserved.

default['murmur']['welcome_text'] = '<br />Welcome to this server running <b>Murmur</b>.<br />Enjoy your stay!<br />'
default['murmur']['server_password'] = ''
default['murmur']['bandwidth'] = 72_000
default['murmur']['users'] = 100
default['murmur']['opus_threshold'] = 100
default['murmur']['register_name'] = 'Mumble Server'

default['caddy']['download_url'] = 'https://caddyserver.com/download/linux/amd64?license=personal&telemetry=off'
default['caddy']['checksum'] = ''
default['caddy']['wwwroot'] = ''
default['caddy']['site'] = ''

default['acme']['contact'] = []
default['acme']['endpoint'] = 'https://acme-staging.api.letsencrypt.org'
default['acme']['site'] = ''
default['acme']['sans'] = []
default['acme']['wwwroot'] = ''

default['fivem']['download_url'] = ''
default['fivem']['tags'] = 'default'
default['fivem']['hostname'] = 'My new FXServer!'
default['fivem']['admin'] = 'identifier.steam:110000112345678'
default['fivem']['license_key'] = ''
default['fivem']['vmenu_url'] = ''
