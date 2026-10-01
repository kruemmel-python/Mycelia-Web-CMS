/* 
 * Mycelia Security SDK
 * Copyright (c) 2025 Mycelia Security
 * Header Definition v1.0
 */

#ifndef MYCELIA_SDK_H
#define MYCELIA_SDK_H

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
    #ifdef MYCELIA_EXPORTS
        #define MY_API __declspec(dllexport)
    #else
        #define MY_API __declspec(dllimport)
    #endif
#else
    #define MY_API __attribute__((visibility("default")))
#endif

// Opaque Handle: Der Nutzer sieht nicht, was drin steckt.
typedef struct MyceliaContext_T* myc_context_t;

// Standardisierte Fehlercodes
typedef enum {
    MYC_SUCCESS = 0,
    MYC_ERR_UNKNOWN = -1,
    MYC_ERR_NO_GPU = -2,
    MYC_ERR_INIT_FAILED = -3,
    MYC_ERR_INVALID_PARAM = -4,
    MYC_ERR_BUFFER_TOO_SMALL = -5,
    MYC_ERR_OPENCL = -6
} myc_result;

#ifdef __cplusplus
extern "C" {
#endif

    /* --- System Management --- */
    
    // Initialisiert das Subsystem. Muss vor allem anderen gerufen werden.
    MY_API myc_result myc_init();

    // Gibt die Anzahl der verfügbaren GPUs zurück.
    MY_API int myc_get_device_count();

    // Holt die letzte Fehlermeldung (Thread-Safe).
    MY_API const char* myc_get_last_error();


    /* --- Context Management --- */

    // Erstellt eine Instanz auf einer bestimmten GPU.
    MY_API myc_result myc_create_context(int gpu_index, myc_context_t* out_ctx);

    // Gibt Speicher und GPU-Ressourcen frei.
    MY_API void myc_destroy_context(myc_context_t ctx);


    /* --- Cryptography Operations --- */

    // Legacy 64-bit seed path. Retained only for backward-compatible decryption
    // of MCMS1 records. New callers MUST use myc_set_key_256.
    MY_API myc_result myc_set_seed(myc_context_t ctx, uint64_t seed);

    // Sets a full 256-bit record key. The key is used both to domain-separate
    // the Mycelia GPU stream and to apply a HMAC-SHA256 derived stream mask.
    // key_len must be exactly 32 bytes.
    MY_API myc_result myc_set_key_256(myc_context_t ctx, const uint8_t* key, size_t key_len);

    // Returns a stable capability string for fail-closed ABI negotiation.
    MY_API const char* myc_get_security_capabilities();

    // Verschlüsselt/Entschlüsselt einen Datenblock (In-Place).
    // data: Pointer zu den Rohdaten (wird überschrieben mit Ciphertext/Plaintext)
    // len: Länge der Daten in Bytes
    // stream_offset: Position in der Gesamtdatei (für CTR-Mode wichtig!)
    MY_API myc_result myc_process_buffer(myc_context_t ctx, uint8_t* data, size_t len, size_t stream_offset);

#ifdef __cplusplus
}
#endif

#endif // MYCELIA_SDK_H