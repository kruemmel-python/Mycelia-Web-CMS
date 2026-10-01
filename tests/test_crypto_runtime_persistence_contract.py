from pathlib import Path


def test_prebuilt_crypto_runtime_is_immutable_install_source() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "build_security_sdk.ps1").read_text(encoding="utf-8-sig")

    assert "Copy-Item $outDll $prebuiltDll -Force" not in script
    assert "Copy-Item $prebuiltDll $vendorDll -Force" in script
    assert "Persistenz-Runtime gepinnt" in script


def test_pinned_crypto_runtime_is_shipped() -> None:
    root = Path(__file__).resolve().parents[1]
    prebuilt = root / "third_party" / "prebuilt" / "CC_OpenCl.dll"
    vendor = root / "vendor" / "CC_OpenCl.dll"

    assert prebuilt.is_file() and prebuilt.stat().st_size > 0
    assert vendor.is_file() and vendor.stat().st_size > 0
    assert prebuilt.read_bytes() == vendor.read_bytes()
