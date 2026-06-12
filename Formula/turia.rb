class Turia < Formula
  desc "CLI para desarrollo móvil"
  homepage "https://github.com/rudoapps/homebrew-turia"
  url "https://github.com/rudoapps/homebrew-turia/archive/refs/tags/v0.0.1.tar.gz"
  sha256 "3e8733f555cebcf1ed9a0c664456713ebea1c8dec5264da8d4c8239d3359e7f4"
  license "MIT"

  depends_on "jq"
  depends_on "python@3.12"  # Required by turia ai (CLI agent)
  depends_on "glow" => :recommended  # For better markdown/table rendering

  def install
    # Instalar script principal
    bin.install "turia"

    # Instalar VERSION file (single source of truth for version)
    prefix.install "VERSION"

    # Instalar scripts en opt/turia/scripts (donde el script los busca)
    prefix.install "scripts"
  end

  test do
    system "#{bin}/turia", "--help"
  end
end
