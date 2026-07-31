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
import java.util.concurrent.atomic.AtomicReference

/** Android adapter for the serialized ConfigServer lifecycle coordinator. */
object ConfigServerManager {

    private const val TAG = "ConfigServerManager"
    private const val MAX_PORT_RETRY = 10
    private const val STOP_TIMEOUT_MS = 750L

    private data class ManagedServer(
        val generation: Long,
        val value: ConfigServer
    )

    private data class ManagedNetworkCallback(
        val generation: Long,
        val value: ConnectivityManager.NetworkCallback
    )

    @Volatile
    private var server: ManagedServer? = null

    private val serverLock = Any()
    private var retiredServerGeneration = 0L
    private val callbackLock = Any()
    private var retiredCallbackGeneration = 0L
    private var networkCallback: ManagedNetworkCallback? = null
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

        override fun currentListeningPort(generation: Long?): Int? = server
            ?.takeIf { generation == null || it.generation == generation }
            ?.value
            ?.takeIf { it.isAlive }
            ?.listeningPort
            ?.takeIf { it > 0 }

        override fun startServer(generation: Long): Int? {
            val context = appContext ?: return null
            currentListeningPort(generation)?.let { return it }

            for (port in ConfigServer.PORT until ConfigServer.PORT + MAX_PORT_RETRY) {
                var candidate: ConfigServer? = null
                try {
                    candidate = ConfigServer(context, port)
                    candidate.start()
                    val listeningPort = candidate.listeningPort
                    if (candidate.isAlive && listeningPort > 0) {
                        var displaced: ManagedServer? = null
                        val installed = synchronized(serverLock) {
                            val active = server
                            if (generation <= retiredServerGeneration || (active != null && active.generation > generation)) {
                                false
                            } else {
                                displaced = active
                                server = ManagedServer(generation, candidate)
                                true
                            }
                        }
                        if (!installed) {
                            boundedStop(candidate)
                            return null
                        }
                        displaced?.value?.takeIf { it !== candidate }?.let(::stopDetached)
                        XLog.i(TAG, "config_server.bound event=start port=$listeningPort")
                        return listeningPort
                    }
                    boundedStop(candidate)
                } catch (error: Exception) {
                    candidate?.let(::boundedStop)
                    XLog.e(TAG, "config_server.start_failed port=$port error=${error.javaClass.simpleName}")
                }
            }
            XLog.e(TAG, "config_server.start_failed reason=no_available_port")
            return null
        }

        override fun stopServer(upToGeneration: Long): ConfigServerStopOutcome {
            val activeServer = synchronized(serverLock) {
                retiredServerGeneration = maxOf(retiredServerGeneration, upToGeneration)
                server?.takeIf { it.generation <= upToGeneration }?.also { server = null }
            }
            return activeServer?.value?.let(::boundedStop) ?: ConfigServerStopOutcome.STOPPED
        }

        override fun registerNetworkCallback(generation: Long) {
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
                var displaced: ManagedNetworkCallback? = null
                val installed = synchronized(callbackLock) {
                    val active = networkCallback
                    if (generation <= retiredCallbackGeneration || (active != null && active.generation > generation)) {
                        false
                    } else {
                        displaced = active
                        networkCallback = ManagedNetworkCallback(generation, callback)
                        true
                    }
                }
                if (!installed) {
                    unregisterCallback(connectivityManager, callback)
                    return
                }
                displaced?.value?.takeIf { it !== callback }?.let {
                    unregisterCallback(connectivityManager, it)
                }
                XLog.i(TAG, "config_server.callback event=registered generation=$generation")
            } catch (error: Exception) {
                XLog.e(TAG, "config_server.callback_register_failed error=${error.javaClass.simpleName}")
            }
        }

        override fun unregisterNetworkCallback(upToGeneration: Long) {
            val callback = synchronized(callbackLock) {
                retiredCallbackGeneration = maxOf(retiredCallbackGeneration, upToGeneration)
                networkCallback
                    ?.takeIf { it.generation <= upToGeneration }
                    ?.also { networkCallback = null }
            }
            val connectivityManager = appContext
                ?.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            if (callback != null && connectivityManager != null) {
                unregisterCallback(connectivityManager, callback.value)
            }
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
            if (current.generation < _state.value.generation) return
            _state.value = current
            XLog.i(
                TAG,
                "config_server.transition event=$reason previous=${previous.phase} new=${current.phase} generation=${current.generation}"
            )
            _configChanged.tryEmit(Unit)
        }
    }

    private fun stopDetached(value: ConfigServer) {
        Thread(
            { boundedStop(value) },
            "lumi-config-server-displaced-stop"
        ).apply {
            isDaemon = true
            start()
        }
    }

    private fun boundedStop(value: ConfigServer): ConfigServerStopOutcome {
        val failure = AtomicReference<Throwable?>(null)
        val worker = Thread(
            {
                try {
                    value.stop()
                } catch (error: Throwable) {
                    failure.set(error)
                }
            },
            "lumi-config-server-nanohttpd-stop"
        ).apply { isDaemon = true }
        worker.start()
        return try {
            worker.join(STOP_TIMEOUT_MS)
            when {
                worker.isAlive -> {
                    XLog.e(TAG, "config_server.stop_timeout timeout_ms=$STOP_TIMEOUT_MS")
                    ConfigServerStopOutcome.TIMED_OUT
                }
                failure.get() != null -> {
                    XLog.e(TAG, "config_server.stop_failed error=${failure.get()!!.javaClass.simpleName}")
                    ConfigServerStopOutcome.FAILED
                }
                else -> ConfigServerStopOutcome.STOPPED
            }
        } catch (error: InterruptedException) {
            Thread.currentThread().interrupt()
            XLog.e(TAG, "config_server.stop_interrupted")
            ConfigServerStopOutcome.FAILED
        }
    }

    private fun unregisterCallback(
        connectivityManager: ConnectivityManager,
        callback: ConnectivityManager.NetworkCallback
    ) {
        try {
            connectivityManager.unregisterNetworkCallback(callback)
        } catch (error: Exception) {
            XLog.e(TAG, "config_server.callback_unregister_failed error=${error.javaClass.simpleName}")
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
        server?.value?.isAlive == true

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
