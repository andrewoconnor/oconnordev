user 'jekyll' do
  system true
  home '/opt/jekyll'
  manage_home false
  shell '/usr/sbin/nologin'
end

directory '/opt/jekyll' do
  owner 'jekyll'
  group 'jekyll'
  action :create
end

rbenv_user_install 'jekyll' do
  user 'jekyll'
end

ruby_version = '2.6.0'

rbenv_ruby ruby_version do
  user 'jekyll'
end

gem_opts = '--no-document'

rbenv_gem 'bundler' do
  options gem_opts
  rbenv_version ruby_version
  user 'jekyll'
end

rbenv_gem 'jekyll' do
  options gem_opts
  rbenv_version ruby_version
  user 'jekyll'
end

rbenv_rehash 'rehash' do
  user 'jekyll'
end

git '/opt/jekyll/online-cv' do
  repository 'https://github.com/sharu725/online-cv'
  user 'jekyll'
  group 'jekyll'
end

rbenv_script 'new onlinecv' do
  rbenv_version ruby_version
  user 'jekyll'
  code 'jekyll new /opt/jekyll/onlinecv'
end

# rbenv_script 'build onlinecv' do
#   rbenv_version ruby_version
#   user 'jekyll'
#   code 'jekyll build --source /opt/jekyll/onlinecv --destination /soft/oconnordev/onlinecv'
# end
