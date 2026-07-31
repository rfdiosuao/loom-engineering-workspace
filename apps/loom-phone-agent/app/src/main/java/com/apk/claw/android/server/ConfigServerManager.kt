package com.apk.claw.android.server

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface

/** Android adapter for the serialized ConfigServer lifecycle coordinator. */
object ConfigServerManager {

    private const val TAG = "ConfigServerManager"
    private const val MAX_PORT_RETRY = 10

    @Volatile
    private var server: ConfigServer? = null

    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var appContext: Context? = null

    private val _configChanged = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val configChanged: SharedFlow<Unit> = _configChanged.asSharedFlow()

    private val _state = MutableStateFlow(ConfigServerState())
    val state: StateFlow<ConfigServerState> = _state

    private lateinit var lifecycle: ConfigServerLifecycleCoordinator

    private val lifecycleEffects = object : ConfigServerLifecycleEffects {
        override fun isDesiredEnabled(): Boolean = KVUtils.isConfigServerEnabled()

        override fun persistEnabled(enabled: Boolean) {
            KVUtils.setConfigServerEnabled(enabled)
        }

        override fun currentListeningPort(): Int? = server
            ?.takeIf { it.isAlive }
            ?.listeningPort
            ?.takeIf { it > 0 }

        override fun startServer(): Int? {
            val context = appContext ?: return null
            currentListeningPort()?.let { return it }

            for (port in ConfigServer.PORT until ConfigServer.PORT + MAX_PORT_RETRY) {
                var candidate: ConfigServer? = null
                try {
                    candidate = ConfigServer(context, port)
                    candidate.start()
                    val listeningPort = candidate.listeningPort
                    if (candidate.isAlive && listeningPort > 0) {
                        server = candidate
                        XLog.i(TAG, "config_server.bound event=start port=$listeningPort")
                        return listeningPort
                    }
                    candidate.stop()
                } catch (error: Exception) {
                    try {
                        candidate?.stop()
                    } catch (_: Exception) {
                        // Best effort only; the next bounded port attempt is still safe.
                    }
                    XLog.e(TAG, "config_server.start_failed port=$port error=${error.javaClass.simpleName}")
                }
            }
            XLog.e(TAG, "config_server.start_failed reason=no_available_port")
            return null
        }

        override fun stopServer() {
            val activeServer = server
            server = null
            try {
                activeServer?.stop()
            } catch (error: Exception) {
                XLog.e(TAG, "config_server.stop_failed error=${error.javaClass.simpleName}")
            }
        }

        override fun registerNetworkCallback(generation: Long) {
            unregisterNetworkCallback()
            val context = appContext ?: return
            val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
            val callback = object : ConnectivityManager.NetworkCallback() {
                override fun onLost(network: Network) {
                    XLog.i(
                        TAG,
                        "config_server.callback event=lost generation=$generation keeping ConfigServer available for USB loopback"
                    )
                    lifecycle.onNetworkLost(generation)
                }

                override fun onAvailable(network: Network) {
                    XLog.i(TAG, "config_server.callback event=available generation=$generation")
                    lifecycle.onNetworkAvailable(generation)
                }
            }
            try {
                connectivityManager.registerNetworkCallback(NetworkRequest.Builder().build(), callback)
                networkCallback = callback
                XLog.i(TAG, "config_server.callback event=registered generation=$generation")
            } catch (error: Exception) {
                XLog.e(TAG, "config_server.callback_register_failed error=${error.javaClass.simpleName}")
            }
        }

        override fun unregisterNetworkCallback() {
            val callback = networkCallback ?: return
            try {
                val connectivityManager = appContext
                    ?.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                connectivityManager?.unregisterNetworkCallback(callback)
            } catch (error: Exception) {
                XLog.e(TAG, "config_server.callback_unregister_failed error=${error.javaClass.simpleName}")
            }
            networkCallback = null
        }

        override fun onAddressChanged() {
            XLog.i(TAG, "config_server.address_changed generation=${lifecycle.state.generation}")
            _configChanged.tryEmit(Unit)
        }

        override fun onStateChanged(
            previous: ConfigServerState,
            current: ConfigServerState,
            reason: String
        ) {
            _state.value = current
            XLog.i(
                TAG,
                "config_server.transition event=$reason previous=${previous.phase} new=${current.phase} generation=${current.generation}"
            )
            _configChanged.tryEmit(Unit)
        }
    }

    init {
        lifecycle = ConfigServerLifecycleCoordinator(lifecycleEffects)
    }

    fun notifyConfigChanged() {
        _configChanged.tryEmit(Unit)
    }

    /** Runtime start preserves the existing API and does not alter the persisted preference. */
    fun start(context: Context): Boolean {
        appContext = context.applicationContext
        return lifecycle.runtimeStart()
    }

    /** User intent: persist enabled before the service can be started. */
    fun enable(context: Context): Boolean {
        appContext = context.applicationContext
        return lifecycle.userEnable()
    }

    /** Runtime teardown does not change the user's persisted preference. */
    fun stop() {
        lifecycle.runtimeStop()
    }

    /** User intent: persist disabled before callback unregistration or server stop. */
    fun disable() {
        lifecycle.userDisable()
    }

    fun isRunning(): Boolean = lifecycle.state.phase == ConfigServerLifecyclePhase.READY &&
        server?.isAlive == true

    fun getPort(): Int? = if (isRunning()) lifecycle.state.port else null

    fun getAddress(): String? {
        val ip = getLanIpAddress(appContext ?: return null) ?: return null
        val port = getPort() ?: return null
        return "$ip:$port"
    }

    fun autoStartIfNeeded(context: Context) {
        appContext = context.applicationContext
        if (ConfigServerAutoStartPolicy.shouldAutoStart(KVUtils.isConfigServerEnabled(), KVUtils.hasLlmConfig())) {
            lifecycle.startIfDesired()
        }
    }

    fun isWifiConnected(context: Context): Boolean {
        val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = connectivityManager.activeNetwork ?: return false
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }

    fun hasLanAddress(context: Context): Boolean = getLanIpAddress(context) != null

    fun getLanIpAddress(context: Context): String? = getWifiIpAddress(context) ?: getInterfaceIpAddress()

    private fun getWifiIpAddress(context: Context): String? {
        return try {
            val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val ipInt = wifiManager?.connectionInfo?.ipAddress ?: 0
            if (ipInt == 0) return null
            String.format(
                "%d.%d.%d.%d",
                ipInt and 0xff,
                ipInt shr 8 and 0xff,
                ipInt shr 16 and 0xff,
                ipInt shr 24 and 0xff
            ).takeUnless { it == "0.0.0.0" }
        } catch (error: Exception) {
            XLog.e(TAG, "config_server.wifi_ip_failed error=${error.javaClass.simpleName}")
            null
        }
    }

    private fun getInterfaceIpAddress(): String? {
        return try {
            NetworkInterface.getNetworkInterfaces()?.toList()
                ?.filter { it.isUp && !it.isLoopback && !it.isVirtual }
                ?.filterNot { PhoneNetworkMode.isCellularOnly(it.name) }
                ?.flatMap { networkInterface ->
                    networkInterface.inetAddresses.toList()
                        .filterIsInstance<Inet4Address>()
                        .filter(::isUsableLanAddress)
                        .map { address -> networkInterface.name to address.hostAddress }
                }
                ?.sortedWith(compareBy<Pair<String, String>>({ PhoneNetworkMode.interfacePriority(it.first) }, { it.first }))
                ?.firstOrNull()
                ?.second
        } catch (error: Exception) {
            XLog.e(TAG, "config_server.interface_ip_failed error=${error.javaClass.simpleName}")
            null
        }
    }

    private fun isUsableLanAddress(address: InetAddress): Boolean {
        return !address.isLoopbackAddress &&
            !address.isAnyLocalAddress &&
            !address.isLinkLocalAddress &&
            address.isSiteLocalAddress
    }
}
