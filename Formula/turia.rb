class Turia < Formula
  desc "CLI para desarrollo móvil"
  homepage "https://github.com/rudoapps/turia"
  url "https://github.com/rudoapps/homebrew-turia/archive/refs/tags/v0.0.1.tar.gz"
  sha256 "PENDIENTE_PRIMER_RELEASE"  # rellenar con el sha256 del tarball del primer tag
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
