#
# Cookbook:: calusari
# Recipe:: mumble
#
# Copyright:: 2018, The Authors, All Rights Reserved.

apt_repository 'mumble' do
  uri 'ppa:mumble/snapshot'
  keyserver 'keyserver.ubuntu.com'
  key '7F05CF9E'
end

apt_package 'mumble-server'
