#!/bin/bash


check_os() {
    case "$(uname -s)" in
        Darwin)
            echo "macOS"
            ;;
        Linux)
            echo "Linux"
            ;;
        CYGWIN*|MINGW32*|MSYS*|MINGW*)
            echo "Windows"
            ;;
        *)
            echo "Unknown OS"
            ;;
    esac
}