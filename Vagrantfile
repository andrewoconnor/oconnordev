Vagrant.configure(2) do |config|
  config.vm.box = 'ubuntu/xenial64'
  config.vm.network 'private_network', type: 'dhcp'
  config.vm.network 'forwarded_port', guest: 80, host: 8080

  config.vm.provider 'virtualbox' do |vb|
    vb.memory = '2048'
    vb.cpus = '2'
  end
end
