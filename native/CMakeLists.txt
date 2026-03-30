cmake_minimum_required(VERSION 3.21)

project(framelab_native_backend
    VERSION 0.2.0
    DESCRIPTION "FrameLab native backend"
    LANGUAGES C
)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Single-config generators honor CMAKE_BUILD_TYPE. Multi-config generators
# (Visual Studio, Xcode) ignore it and require --config at build time.
if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(FRAMELAB_BUILD_TOOLS "Build CLI/demo tools" ON)
if(MSVC)
    set(FRAMELAB_ENABLE_IPO_DEFAULT OFF)
else()
    set(FRAMELAB_ENABLE_IPO_DEFAULT ON)
endif()
option(
    FRAMELAB_ENABLE_IPO
    "Enable interprocedural optimization (LTO/IPO) for Release-like configs when supported"
    ${FRAMELAB_ENABLE_IPO_DEFAULT}
)
option(FRAMELAB_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(FRAMELAB_BUILD_PYTHON_MODULE "Build the Python extension module (_native)" ON)
set(FRAMELAB_PYTHON_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../framelab/native" CACHE PATH "Directory for the built Python extension")

set(FRAMELAB_CORE_HEADERS
    include/framelab_native/api.h
    include/framelab_native/common/types.h
    include/framelab_native/common/status.h
    include/framelab_native/common/pixel_formats.h
    include/framelab_native/common/stride.h
    include/framelab_native/common/roi.h
    include/framelab_native/common/dispatch.h
    include/framelab_native/decode/decode.h
    include/framelab_native/decode/mono_unpacked.h
    include/framelab_native/decode/mono_packed.h
    include/framelab_native/decode/bayer_unpacked.h
    include/framelab_native/decode/bayer_packed.h
    include/framelab_native/decode/packed_bits.h
    include/framelab_native/metrics/metrics.h
    include/framelab_native/metrics/app_metrics.h
    include/framelab_native/metrics/stats.h
    include/framelab_native/metrics/histogram.h
    include/framelab_native/metrics/background.h
    include/framelab_native/metrics/roi_stats.h
    include/framelab_native/loaders/raw_loader.h
    include/framelab_native/loaders/tiff_hook.h
)

set(FRAMELAB_API_SOURCES
    src/api/py_module.c
    src/api/python_bridge.c
)

set(FRAMELAB_CORE_SOURCES
    src/common/status.c
    src/common/pixel_formats.c
    src/common/stride.c
    src/common/dispatch.c
    src/common/roi.c
    src/decode/decode.c
    src/decode/mono_unpacked.c
    src/decode/mono_packed.c
    src/decode/bayer_unpacked.c
    src/decode/bayer_packed.c
    src/decode/packed_bits.c
    src/loaders/raw_loader.c
    src/loaders/tiff_hook.c
    src/metrics/stats.c
    src/metrics/app_metrics.c
    src/metrics/fused_metrics.c
    src/metrics/background.c
    src/metrics/roi_stats.c
    src/metrics/histogram.c
)

add_library(framelab_native STATIC
    ${FRAMELAB_CORE_HEADERS}
    ${FRAMELAB_CORE_SOURCES}
)

target_include_directories(framelab_native
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_features(framelab_native PUBLIC c_std_11)

# Helpful IDE grouping.
source_group(TREE "${CMAKE_CURRENT_SOURCE_DIR}" FILES
    ${FRAMELAB_CORE_HEADERS}
    ${FRAMELAB_CORE_SOURCES}
    ${FRAMELAB_API_SOURCES}
)

if(MSVC)
    target_compile_options(framelab_native PRIVATE
        /W4
        /permissive-
        /Zc:preprocessor
    )
    target_compile_definitions(framelab_native PRIVATE
        _CRT_SECURE_NO_WARNINGS
    )
    if(FRAMELAB_WARNINGS_AS_ERRORS)
        target_compile_options(framelab_native PRIVATE /WX)
    endif()
else()
    target_compile_options(framelab_native PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Wshadow
        -Wconversion
        -Wstrict-prototypes
    )
    if(FRAMELAB_WARNINGS_AS_ERRORS)
        target_compile_options(framelab_native PRIVATE -Werror)
    endif()
endif()

# libm is needed on many Unix-like toolchains, but not on MSVC.
if(NOT MSVC)
    target_link_libraries(framelab_native PUBLIC m)
endif()

if(FRAMELAB_ENABLE_IPO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT FRAMELAB_IPO_SUPPORTED OUTPUT FRAMELAB_IPO_OUTPUT)

    if(FRAMELAB_IPO_SUPPORTED)
        if(CMAKE_CONFIGURATION_TYPES)
            set_property(TARGET framelab_native PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
            set_property(TARGET framelab_native PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELWITHDEBINFO TRUE)
        elseif(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
            set_property(TARGET framelab_native PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
        endif()
    else()
        message(STATUS "IPO/LTO not supported: ${FRAMELAB_IPO_OUTPUT}")
    endif()
endif()

if(FRAMELAB_BUILD_PYTHON_MODULE)
    find_package(Python3 COMPONENTS Interpreter Development.Module NumPy REQUIRED)

    Python3_add_library(_native MODULE
        ${FRAMELAB_API_SOURCES}
    )

    target_include_directories(_native PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/src/api
    )
    target_include_directories(_native SYSTEM PRIVATE
        ${Python3_INCLUDE_DIRS}
        ${Python3_NumPy_INCLUDE_DIRS}
    )
    target_link_libraries(_native PRIVATE
        framelab_native
        Python3::Module
    )
    target_compile_features(_native PRIVATE c_std_11)
    set_target_properties(_native PROPERTIES
        PREFIX ""
        OUTPUT_NAME "_native"
    )

    if(MSVC)
        target_compile_options(_native PRIVATE /W4 /permissive- /Zc:preprocessor /wd4200)
        target_compile_definitions(_native PRIVATE _CRT_SECURE_NO_WARNINGS)
        if(FRAMELAB_WARNINGS_AS_ERRORS)
            target_compile_options(_native PRIVATE /WX)
        endif()
    else()
        # The Python and NumPy C APIs intentionally use extension patterns that
        # GCC reports under -Wpedantic, which drowns out warnings in our code.
        target_compile_options(_native PRIVATE -Wall -Wextra -Wshadow -Wconversion -Wstrict-prototypes)
        if(FRAMELAB_WARNINGS_AS_ERRORS)
            target_compile_options(_native PRIVATE -Werror)
        endif()
    endif()

    if(FRAMELAB_ENABLE_IPO AND FRAMELAB_IPO_SUPPORTED)
        if(CMAKE_CONFIGURATION_TYPES)
            set_property(TARGET _native PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
            set_property(TARGET _native PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELWITHDEBINFO TRUE)
        elseif(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
            set_property(TARGET _native PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
        endif()
    endif()

    if(FRAMELAB_PYTHON_OUTPUT_DIR)
        foreach(_cfg DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
            set_target_properties(_native PROPERTIES
                LIBRARY_OUTPUT_DIRECTORY_${_cfg} "${FRAMELAB_PYTHON_OUTPUT_DIR}"
                RUNTIME_OUTPUT_DIRECTORY_${_cfg} "${FRAMELAB_PYTHON_OUTPUT_DIR}"
            )
        endforeach()
        set_target_properties(_native PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY "${FRAMELAB_PYTHON_OUTPUT_DIR}"
            RUNTIME_OUTPUT_DIRECTORY "${FRAMELAB_PYTHON_OUTPUT_DIR}"
        )
    endif()
endif()

if(FRAMELAB_BUILD_TOOLS)
    set(FRAMELAB_METRICS_DEMO_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/tools/fl_metrics_demo.c")

    if(EXISTS "${FRAMELAB_METRICS_DEMO_SOURCE}")
        add_executable(fl_metrics_demo "${FRAMELAB_METRICS_DEMO_SOURCE}")
        target_include_directories(fl_metrics_demo PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
        target_link_libraries(fl_metrics_demo PRIVATE framelab_native)

        if(MSVC)
            target_compile_options(fl_metrics_demo PRIVATE
                /W4
                /permissive-
                /Zc:preprocessor
            )
            target_compile_definitions(fl_metrics_demo PRIVATE
                _CRT_SECURE_NO_WARNINGS
            )
            if(FRAMELAB_WARNINGS_AS_ERRORS)
                target_compile_options(fl_metrics_demo PRIVATE /WX)
            endif()
        else()
            target_compile_options(fl_metrics_demo PRIVATE
                -Wall
                -Wextra
                -Wpedantic
                -Wshadow
                -Wconversion
                -Wstrict-prototypes
            )
            if(FRAMELAB_WARNINGS_AS_ERRORS)
                target_compile_options(fl_metrics_demo PRIVATE -Werror)
            endif()
        endif()

        if(FRAMELAB_ENABLE_IPO AND FRAMELAB_IPO_SUPPORTED)
            if(CMAKE_CONFIGURATION_TYPES)
                set_property(TARGET fl_metrics_demo PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE TRUE)
                set_property(TARGET fl_metrics_demo PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELWITHDEBINFO TRUE)
            elseif(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
                set_property(TARGET fl_metrics_demo PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
            endif()
        endif()
    else()
        message(STATUS "FRAMELAB_BUILD_TOOLS=ON, but tools/fl_metrics_demo.c was not found. Skipping demo tool.")
    endif()
endif()

message(STATUS "----------------------------------------")
message(STATUS "FrameLab native backend configuration")
message(STATUS "  System            : ${CMAKE_SYSTEM_NAME}")
message(STATUS "  Processor         : ${CMAKE_SYSTEM_PROCESSOR}")
message(STATUS "  Compiler          : ${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}")
if(CMAKE_CONFIGURATION_TYPES)
    message(STATUS "  Generator configs : ${CMAKE_CONFIGURATION_TYPES}")
else()
    message(STATUS "  Build type        : ${CMAKE_BUILD_TYPE}")
endif()
message(STATUS "  Build tools       : ${FRAMELAB_BUILD_TOOLS}")
message(STATUS "  Build Python mod  : ${FRAMELAB_BUILD_PYTHON_MODULE}")
message(STATUS "  IPO/LTO requested : ${FRAMELAB_ENABLE_IPO}")
if(DEFINED FRAMELAB_IPO_SUPPORTED)
    message(STATUS "  IPO/LTO supported : ${FRAMELAB_IPO_SUPPORTED}")
endif()
message(STATUS "----------------------------------------")
