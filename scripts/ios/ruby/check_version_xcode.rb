#!/usr/bin/env ruby

require 'xcodeproj'

def find_xcode_project
  xcode_project_path = Dir.glob("*.xcodeproj").first
  if xcode_project_path.nil?
    puts "❌ No se encontró ningún archivo .xcodeproj en el directorio actual."
    exit 1
  end
  app_name = File.basename(xcode_project_path, ".xcodeproj")
  puts "✅ Proyecto Xcode encontrado: #{xcode_project_path} (Aplicación: #{app_name})"
  return xcode_project_path
end

def check_xcode_object_version(xcodeproj_path)
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

def main 
  puts ""
  xcodeproj_path = find_xcode_project
  project_created_with_xcode = check_xcode_object_version(xcodeproj_path)

  if project_created_with_xcode == 15
    puts ""
    puts "-----------------------------------------------"
    puts "❌ No se puede usar con proyectos creados con xcode 15 o inferior"
    puts "-----------------------------------------------"
    exit 1
  end
end
main