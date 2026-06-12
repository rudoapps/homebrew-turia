#!/usr/bin/env ruby

require 'xcodeproj'
require 'fileutils'
require_relative 'turia_dependencies.rb'

def xcode_version
  version_output = `xcodebuild -version`
  version = version_output.lines.first.strip.split(' ').last
  version
  puts "ℹ️  Xcode Version: #{version}"
end

def check_object_version(xcodeproj_path)
  pbxproj_path = "#{xcodeproj_path}/project.pbxproj"
  object_version_line = File.readlines(pbxproj_path).grep(/objectVersion/).first

  if object_version_line
    object_version = object_version_line.scan(/\d+/).first.to_i
    puts "ℹ️  Object Version: #{object_version}"
    
    if object_version > 76
      puts "✅ Proyecto creado con xcode 16+"
      return 16
    else
      puts "✅ Proyecto creado con xcode 15 o inferior."
      return 15
    end
    puts ""
  else
    puts "❌ No se encontró 'objectVersion' en el archivo."
    exit 1
  end
end

def find_xcode_project_and_app_name
  xcode_project_path = Dir.glob("*.xcodeproj").first
  if xcode_project_path.nil?
    puts "❌ No se encontró ningún archivo .xcodeproj en el directorio actual."
    exit 1
  end
  app_name = File.basename(xcode_project_path, ".xcodeproj")
  puts "✅ Proyecto Xcode encontrado: #{xcode_project_path} (Aplicación: #{app_name})"
  return xcode_project_path, app_name
end

def copy_all_files(origin, destination)
  if Dir.exist?(destination)
    # Verificar si FORCE_INSTALL está activado
    force_install = ENV['FORCE_INSTALL'] == 'true'

    if force_install
      puts "⚠️  Directorio ya existe, actualizando con --force..."
    else
      puts"-----------------------------------------------"
      puts "Directorio '#{destination}' ya existe. ¿Deseas reemplazarlo? (s/n)"
      puts"-----------------------------------------------"
      response = STDIN.gets

      # Manejar caso cuando STDIN.gets devuelve nil (no hay entrada)
      if response.nil?
        puts "❌ No se pudo obtener respuesta. Usa --force para reinstalar automáticamente."
        return
      end

      response = response.chomp.downcase
      if response == 's'
        puts "Actualizando código..."
      else
        return
      end
    end
  end
  FileUtils.mkdir_p(destination)
  Dir.glob("#{origin}/**/*").each do |item|
    relative_path = item.sub("#{origin}/", "")
    destination_path = File.join(destination, relative_path)
    if File.directory?(item)
      FileUtils.mkdir_p(destination_path)
    else
      FileUtils.mkdir_p(File.dirname(destination_path))

      # Intentar copiar con retry para manejar timeouts temporales
      max_retries = 3
      retry_count = 0
      success = false

      while retry_count < max_retries && !success
        begin
          FileUtils.cp(item, destination_path)
          puts "✅ Código añadido en: #{destination_path}"
          success = true
        rescue Errno::ETIMEDOUT => e
          retry_count += 1
          if retry_count < max_retries
            puts "⚠️  Timeout al copiar #{item}, reintentando (#{retry_count}/#{max_retries})..."
            sleep 0.5
          else
            puts "❌ Error: No se pudo copiar #{item} después de #{max_retries} intentos"
            raise e
          end
        end
      end
    end
  end
end

def create_groups(xcodeproj_path, app_name, destination, destination_relative_path)
  project = Xcodeproj::Project.open(xcodeproj_path)
  root_group = project.main_group.find_subpath(app_name, false) || project.main_group.new_group(app_name, app_name)
  groups = destination_relative_path.split('/')
  current_group = root_group

  groups.each do |group_name|
    current_group = current_group.find_subpath(group_name, false) || current_group.new_group(group_name, group_name)
  end

  Dir.glob("#{destination}/**/*").each do |item|
    next if File.extname(item) == ".turia"
    next if File.directory?(item)
    relative_path = item.sub("#{destination}/", "")
    path_components = relative_path.split("/")
    group = current_group

    path_components.each do |component|
      if File.extname(component).empty?
        group = group.find_subpath(component, false) || group.new_group(component, component)
      end
    end
    

    file_name = File.basename(item)
    
    #if !File.directory?(item)
      existing_ref = group.files.find { |f| f.path == file_name }
      if !existing_ref        
        file_ref = group.new_reference(file_name)
        project.targets.first.add_file_references([file_ref])
        puts "✅ Referencia añadida: #{file_name} en el grupo: #{group.name}"
      end
    #end
  end
  project.save
end

def main 
  xcode_version
  
  xcodeproj_path, app_name = find_xcode_project_and_app_name
  project_created_with_xcode = check_object_version(xcodeproj_path)
  origin = ARGV[0]
  destination_relative_path = ARGV[1]
  temporary_dir = ARGV[2]
  destination = "#{app_name}/#{destination_relative_path}"
  puts "✅ Copiando desde #{origin} hacia #{destination}"
  copy_all_files(origin, destination)

  puts "✅ Archivos copiados exitosamente de #{origin} a #{destination}"

  puts "✅ Integrando en el proyecto Xcode: #{xcodeproj_path}"
  if project_created_with_xcode == 15
    create_groups(xcodeproj_path, app_name, destination, destination_relative_path)
  end
  
  puts "✅ Archivos integrados exitosamente en el proyecto Xcode dentro de #{destination_relative_path}"

  read_turia_file_and_install_dependencies(xcodeproj_path, app_name, origin, temporary_dir, project_created_with_xcode)
end
main
