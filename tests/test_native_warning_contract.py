from pathlib import Path


def test_opencl_extension_loader_is_not_used_as_boolean_function_name() -> None:
    source = Path(
        "third_party/Mycelia-Security-SDK_v2_secure/src/mycelia_core.c"
    ).read_text(encoding="utf-8")

    assert "if (clGetExtensionFunctionAddressForPlatform)" not in source
    assert (
        'clGetExtensionFunctionAddressForPlatform(plat, "clSetDefaultDeviceCommandQueue")'
        in source
    )
    assert (
        'clGetExtensionFunctionAddressForPlatform(plat, "clCreateCommandQueueWithProperties")'
        in source
    )
