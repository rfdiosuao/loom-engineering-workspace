package com.apk.claw.android.utils

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stores long-lived phone pairing credentials encrypted by AndroidKeyStore.
 *
 * Existing MMKV plaintext is migrated transactionally: the caller removes the
 * legacy value only after the encrypted SharedPreferences commit succeeds.
 */
object PhoneCredentialVault {
    private const val TAG = "PhoneCredentialVault"
    private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
    private const val CIPHER_TRANSFORMATION = "AES/GCM/NoPadding"
    private const val STORAGE_NAME = "lumi_phone_credentials"
    private const val ENVELOPE_VERSION = "v1"
    private const val GCM_TAG_BITS = 128
    private const val KEY_ALIAS_SUFFIX = ".phone-pairing.v1"

    private lateinit var preferences: SharedPreferences
    private lateinit var keyAlias: String

    @Synchronized
    fun init(context: Context) {
        val appContext = context.applicationContext
        preferences = appContext.getSharedPreferences(STORAGE_NAME, Context.MODE_PRIVATE)
        keyAlias = appContext.packageName + KEY_ALIAS_SUFFIX
    }

    @Synchronized
    fun get(
        key: String,
        migratePlaintext: () -> String,
        clearPlaintext: () -> Unit,
    ): String {
        val envelope = preferences.getString(key, "").orEmpty()
        if (envelope.isNotBlank()) {
            val decrypted = decrypt(envelope)
            if (decrypted != null) return decrypted
            val legacy = migratePlaintext()
            if (legacy.isNotBlank()) return legacy
            return ""
        }

        val plaintext = migratePlaintext()
        if (plaintext.isBlank()) return ""
        if (put(key, plaintext)) {
            clearPlaintext()
        }
        // Migration is opportunistic. A transient KeyStore/storage failure
        // must not invalidate a credential that remains available in MMKV.
        return plaintext
    }

    @Synchronized
    fun put(key: String, value: String): Boolean {
        return putAll(mapOf(key to value))
    }

    @Synchronized
    fun putAll(values: Map<String, String>): Boolean {
        val encrypted = linkedMapOf<String, String?>()
        return try {
            values.forEach { (key, value) ->
                encrypted[key] = if (value.isBlank()) null else encrypt(value)
            }
            val editor = preferences.edit()
            encrypted.forEach { (key, envelope) ->
                if (envelope == null) editor.remove(key) else editor.putString(key, envelope)
            }
            editor.commit()
        } catch (error: Exception) {
            Log.e(TAG, "Unable to encrypt phone credentials", error)
            false
        }
    }

    @Synchronized
    fun remove(vararg keys: String) {
        val editor = preferences.edit()
        keys.forEach(editor::remove)
        editor.commit()
    }

    @Synchronized
    fun clear() {
        preferences.edit().clear().commit()
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        (keyStore.getKey(keyAlias, null) as? SecretKey)?.let { return it }

        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER).run {
            init(
                KeyGenParameterSpec.Builder(
                    keyAlias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }

    private fun encrypt(plaintext: String): String {
        val cipher = Cipher.getInstance(CIPHER_TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
        val ciphertext = Base64.encodeToString(
            cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8)),
            Base64.NO_WRAP,
        )
        return "$ENVELOPE_VERSION:$iv:$ciphertext"
    }

    private fun decrypt(envelope: String): String? {
        return try {
            val parts = envelope.split(':', limit = 3)
            require(parts.size == 3 && parts[0] == ENVELOPE_VERSION)
            val iv = Base64.decode(parts[1], Base64.NO_WRAP)
            val ciphertext = Base64.decode(parts[2], Base64.NO_WRAP)
            val cipher = Cipher.getInstance(CIPHER_TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateKey(),
                GCMParameterSpec(GCM_TAG_BITS, iv),
            )
            String(cipher.doFinal(ciphertext), Charsets.UTF_8)
        } catch (error: Exception) {
            Log.e(TAG, "Unable to decrypt phone credential", error)
            null
        }
    }
}
