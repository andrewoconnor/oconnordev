#
# Cookbook:: oconnordev
# Recipe:: gai
#
# Copyright:: 2018, The Authors, All Rights Reserved.

getaddrinfo_precedence 'Prefer IPv4' do
  mask '::ffff:0:0/96'
  value 100
end
