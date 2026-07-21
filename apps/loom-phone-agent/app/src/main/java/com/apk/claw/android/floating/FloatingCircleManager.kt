package com.apk.claw.android.floating

import android.animation.ValueAnimator
import android.app.Application
import android.app.LocaleManager
import android.content.Context
import android.content.res.Configuration
import android.content.res.Resources
import android.graphics.Color
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.animation.DecelerateInterpolator
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.TextView
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.core.content.ContextCompat
import com.blankj.utilcode.util.ThreadUtils
import com.apk.claw.android.R
import com.apk.claw.android.channel.Channel
import com.apk.claw.android.utils.KVUtils
import com.apk.claw.android.utils.XLog
import com.blankj.utilcode.util.BarUtils
import com.lzf.easyfloat.EasyFloat
import com.lzf.easyfloat.enums.ShowPattern
import com.lzf.easyfloat.enums.SidePattern
import com.lzf.easyfloat.interfaces.OnFloatCallbacks
import com.lzf.easyfloat.utils.DisplayUtils
import com.google.android.material.card.MaterialCardView
import java.util.Locale

/**
 * 圆形悬浮窗管理器
 * 使用 EasyFloat 实现可拖动、记录位置的圆形悬浮窗
 * 支持多种状态：等待任务(IDLE)、任务执行中(RUNNING)、任务成功(SUCCESS)、任务失败(ERROR)
 */
object FloatingCircleManager {

    private const val FLOAT_TAG = "circle_float"
    private const val KEY_FLOAT_X = "floating_circle_x"
    private const val KEY_FLOAT_Y = "floating_circle_y"
    private const val AUTO_RESET_DELAY_MS = 5000L // 5秒后自动重置

    /**
     * 悬浮窗状态
     */
    enum class State {
        IDLE,           // 等待任务（默认）
        TASK_NOTIFY,    // 收到任务通知（胶囊展开）
        RUNNING,        // 任务执行中
        SUCCESS,        // 任务完成
        ERROR           // 任务失败
    }

    private var isShowing = false
    private var currentState: State = State.IDLE
    private var currentRound: Int = 0
    private var currentBadge: String = "AI"
    private var currentAction: String? = null
    private var currentToolId: String? = null
    private var currentTraceId: String? = null
    private var currentTargetLabel: String? = null
    private var currentChannel: Channel? = null
    private var moveAnimator: ValueAnimator? = null
    private var visualSerial: Int = 0
    private var logPanelExpanded: Boolean = false
    private val progressHistory = FloatingProgressHistory(capacity = 3)

    private const val TASK_NOTIFY_DURATION_MS = 3000L // 任务通知显示 3 秒后收回

    private val mainHandler = Handler(Looper.getMainLooper())
    private var autoResetRunnable: Runnable? = null
    private var notifyCollapseRunnable: Runnable? = null
    private var pendingTaskText: String = ""

    private var appRef: Application? = null

    enum class FloatingSize(val storageValue: String, val scale: Float) {
        SMALL("small", 0.72f),
        MEDIUM("medium", 0.86f),
        LARGE("large", 1f);

        companion object {
            fun fromStorage(value: String): FloatingSize {
                return entries.firstOrNull { it.storageValue == value } ?: LARGE
            }
        }
    }

    fun getFloatingSize(): FloatingSize {
        return FloatingSize.fromStorage(KVUtils.getFloatingCircleSize())
    }

    fun getFloatingSizeLabel(context: Context): String {
        return when (getFloatingSize()) {
            FloatingSize.SMALL -> context.getString(R.string.floating_size_small)
            FloatingSize.MEDIUM -> context.getString(R.string.floating_size_medium)
            FloatingSize.LARGE -> context.getString(R.string.floating_size_large)
        }
    }

    fun setFloatingSize(size: FloatingSize) {
        KVUtils.setFloatingCircleSize(size.storageValue)
        ThreadUtils.runOnUiThread {
            EasyFloat.getFloatView(FLOAT_TAG)?.let { view ->
                applyFloatingSize(view)
                updateStateView(view, currentState)
                ensureFloatInBounds(view)
            }
        }
    }

    fun isFloatingClickEnabled(): Boolean = KVUtils.isFloatingClickEnabled()

    fun setFloatingClickEnabled(enabled: Boolean) {
        KVUtils.setFloatingClickEnabled(enabled)
        ThreadUtils.runOnUiThread {
            EasyFloat.getFloatView(FLOAT_TAG)?.let { view ->
                updateStateView(view, currentState)
            }
        }
    }

    /**
     * 显示悬浮窗
     * @param application Application 实例
     * @param x 初始位置 X（可选，默认屏幕右边偏中心）
     * @param y 初始位置 Y（可选，默认屏幕中心）
     */
    fun show(
        application: Application,
        x: Int? = null,
        y: Int? = null
    ) {
        if (isShowing) {
            return
        }
        appRef = application

        // 计算默认位置：屏幕中心的右边
        val screenWidth = DisplayUtils.getScreenWidth(application)
        val screenHeight = DisplayUtils.getScreenHeight(application)
        val defaultX = 0
        val defaultY = screenHeight / 2

        // 从本地读取保存的位置
        val savedX = getSavedX() ?: x ?: defaultX
        val savedY = getSavedY() ?: y ?: defaultY

        EasyFloat.with(application)
            .setLayout(R.layout.layout_floating_circle)
            .setShowPattern(ShowPattern.ALL_TIME)
            .setSidePattern(SidePattern.DEFAULT)
            .setGravity(android.view.Gravity.START or android.view.Gravity.TOP, savedX, savedY)
            // Keep drag handling installed; touch passthrough disables all interaction in safe mode.
            .setDragEnable(true)
            .hasEditText(false)
            .setTag(FLOAT_TAG)
            .registerCallbacks(object : OnFloatCallbacks {

                override fun createdResult(
                    isCreated: Boolean,
                    msg: String?,
                    view: View?
                ) {
                    view?.let { applyFloatingSize(it) }
                    // 初始化状态
                    updateStateView(view, currentState)
                    // 布局完成后检测位置，防止圆球卡在屏幕外
                    view?.post {
                        ensureFloatInBounds(view)
                    }
                }

                override fun dismiss() {
                    isShowing = false
                }

                override fun drag(view: View, event: MotionEvent) {
                }

                override fun dragEnd(view: View) {
                    // 拖动结束，修正位置并保存
                    ensureFloatInBounds(view)
                }

                override fun hide(view: View) {
                    isShowing = false
                }

                override fun show(view: View) {
                    isShowing = true
                }

                override fun touchEvent(view: View, event: MotionEvent) {

                }
            })
            .show()
    }

    /**
     * 隐藏悬浮窗
     */
    fun hide() {
        if (isShowing) {
            EasyFloat.dismiss(FLOAT_TAG)
            isShowing = false
        }
    }

    /**
     * 判断是否显示中
     */
    fun isShowing(): Boolean = isShowing

    fun toggleLogPanel() {
        ThreadUtils.runOnUiThread {
            logPanelExpanded = !logPanelExpanded
            EasyFloat.getFloatView(FLOAT_TAG)?.let { view ->
                updateStateView(view, currentState)
                ensureFloatInBounds(view)
            }
        }
    }

    /**
     * 切换到等待任务状态（默认）
     */
    fun setIdleState() {
        ThreadUtils.runOnUiThread {
            currentRound = 0
            currentBadge = "AI"
            currentAction = null
            currentToolId = null
            currentTraceId = null
            currentTargetLabel = null
            setState(State.IDLE)
        }
    }

    /**
     * 显示任务通知：悬浮窗展开为胶囊，显示任务内容，3 秒后自动收回进入 RUNNING 状态。
     * @param taskText 任务文本（会截断显示）
     * @param channel 消息来源渠道
     */
    fun showTaskNotify(taskText: String, channel: Channel) {
        ThreadUtils.runOnUiThread {
            progressHistory.beginTask(1)
            pendingTaskText = taskText
            currentChannel = channel
            currentAction = null
            currentToolId = null
            cancelNotifyCollapse()
            setState(State.TASK_NOTIFY)
            // 3 秒后自动收回为 RUNNING（直接 setState，绕过 TASK_NOTIFY 守卫）
            notifyCollapseRunnable = Runnable {
                setState(State.RUNNING)
            }
            mainHandler.postDelayed(notifyCollapseRunnable!!, TASK_NOTIFY_DURATION_MS)
        }
    }

    private fun cancelNotifyCollapse() {
        notifyCollapseRunnable?.let {
            mainHandler.removeCallbacks(it)
            notifyCollapseRunnable = null
        }
    }

    /**
     * 切换到任务执行中状态
     * @param round 当前轮数
     * @param channel 消息来源渠道（可为 null，如 HTTP API 调用）
     */
    fun setRunningState(round: Int, channel: Channel?) {
        ThreadUtils.runOnUiThread {
            if (round <= 1 && currentState != State.RUNNING && currentState != State.TASK_NOTIFY) {
                progressHistory.beginTask(round)
            } else {
                progressHistory.recordThinking(round)
            }
            currentRound = round
            currentBadge = round.toString()
            currentChannel = channel
            currentAction = null
            currentToolId = null
            currentTraceId = null
            currentTargetLabel = null
            // 如果正在显示任务通知胶囊，只更新数据，不切换 UI（等定时器到期自动切）
            if (currentState == State.TASK_NOTIFY) {
                return@runOnUiThread
            }
            setState(State.RUNNING)
        }
    }

    /**
     * 切换到任务执行中状态（用于 HTTP API，无渠道信息）
     * @param round 当前轮数
     */
    fun setRunningStateFromApi(round: Int) {
        setRunningState(round, null)
    }

    fun setAgentToolProgress(round: Int, toolId: String) {
        ThreadUtils.runOnUiThread {
            progressHistory.recordTool(round, toolId)
            currentRound = round
            currentBadge = round.coerceAtLeast(1).toString()
            currentChannel = null
            currentAction = null
            currentToolId = toolId.lowercase(Locale.US)
            currentTraceId = null
            currentTargetLabel = null
            setState(State.RUNNING)
        }
    }

    /**
     * 显示一次外部 API 动作的可视化指针。
     * 这不会保存悬浮窗位置，避免真实操作坐标覆盖用户拖动设置。
     */
    fun showActionPreview(application: Application, action: String, x: Int, y: Int, traceId: String?) {
        ThreadUtils.runOnUiThread {
            appRef = application
            if (!isShowing) {
                show(application)
            }
            logPanelExpanded = false
            currentChannel = null
            currentAction = action.lowercase(Locale.US)
            currentToolId = null
            currentBadge = actionBadge(action)
            currentTraceId = traceId
            currentTargetLabel = "$x,$y"
            setState(State.RUNNING)
            moveToActionPoint(x, y)
            playActionPreviewAnimation(action)
            XLog.d("FloatingCircleManager", "Action preview action=$action x=$x y=$y trace=${traceId ?: ""}")
        }
    }

    /**
     * 显示滑动动作的可视化：先定位起点，再跟随真实手势移动到终点。
     */
    fun showSwipePreview(
        application: Application,
        startX: Int,
        startY: Int,
        endX: Int,
        endY: Int,
        durationMs: Int,
        traceId: String?,
        startDelayMs: Long
    ) {
        ThreadUtils.runOnUiThread {
            appRef = application
            if (!isShowing) {
                show(application)
            }
            logPanelExpanded = false
            currentChannel = null
            currentAction = "swipe"
            currentToolId = null
            currentBadge = actionBadge("swipe")
            currentTraceId = traceId
            currentTargetLabel = "$startX,$startY -> $endX,$endY"
            setState(State.RUNNING)
            moveToActionPoint(startX, startY)
            playActionPreviewAnimation("swipe")
            mainHandler.postDelayed({
                animateToActionPoint(endX, endY, durationMs.coerceIn(180, 1800).toLong())
            }, startDelayMs)
            XLog.d(
                "FloatingCircleManager",
                "Swipe preview start=($startX,$startY) end=($endX,$endY) duration=$durationMs trace=${traceId ?: ""}"
            )
        }
    }

    /**
     * 显示拖拽动作的可视化：先停在起点，再跟随真实拖拽移动到终点。
     */
    fun showDragPreview(
        application: Application,
        startX: Int,
        startY: Int,
        endX: Int,
        endY: Int,
        holdMs: Int,
        durationMs: Int,
        traceId: String?,
        startDelayMs: Long
    ) {
        ThreadUtils.runOnUiThread {
            appRef = application
            if (!isShowing) {
                show(application)
            }
            logPanelExpanded = false
            currentChannel = null
            currentAction = "drag"
            currentToolId = null
            currentBadge = actionBadge("drag")
            currentTraceId = traceId
            currentTargetLabel = "$startX,$startY -> $endX,$endY"
            setState(State.RUNNING)
            moveToActionPoint(startX, startY)
            playActionPreviewAnimation("drag")
            mainHandler.postDelayed({
                animateToActionPoint(endX, endY, durationMs.coerceIn(180, 2200).toLong())
            }, startDelayMs + holdMs.coerceIn(80, 2000).toLong())
            XLog.d(
                "FloatingCircleManager",
                "Drag preview start=($startX,$startY) end=($endX,$endY) hold=$holdMs duration=$durationMs trace=${traceId ?: ""}"
            )
        }
    }

    /**
     * 显示动作执行结果。若传入坐标，会先把指针移动到该坐标。
     */
    fun showCursorPreview(
        application: Application,
        action: String,
        x: Int,
        y: Int,
        traceId: String?,
        holdMs: Long
    ) {
        ThreadUtils.runOnUiThread {
            appRef = application
            if (!isShowing) {
                show(application)
            }
            logPanelExpanded = false
            currentChannel = null
            currentAction = action.lowercase(Locale.US)
            currentToolId = null
            currentBadge = actionBadge(action)
            currentTraceId = traceId
            currentTargetLabel = "$x,$y"
            setState(State.RUNNING)
            moveToActionPoint(x, y)
            playActionPreviewAnimation(action)
            val serial = visualSerial
            mainHandler.postDelayed({
                if (serial == visualSerial) {
                    setIdleState()
                }
            }, holdMs.coerceIn(800L, 8000L))
            XLog.d("FloatingCircleManager", "Cursor preview action=$action x=$x y=$y trace=${traceId ?: ""}")
        }
    }

    fun showActionResult(success: Boolean, x: Int? = null, y: Int? = null) {
        ThreadUtils.runOnUiThread {
            visualSerial++
            moveAnimator?.cancel()
            if (x != null && y != null) {
                moveToActionPoint(x, y)
            }
            if (success) {
                setState(State.SUCCESS)
                scheduleAutoReset()
            } else {
                setState(State.ERROR)
                scheduleAutoReset()
            }
            playResultAnimation()
        }
    }

    /**
     * 切换到任务完成状态（5秒后自动回到 IDLE）
     */
    fun setSuccessState() {
        ThreadUtils.runOnUiThread {
            progressHistory.recordSuccess()
            setState(State.SUCCESS)
            scheduleAutoReset()
        }
    }

    /**
     * 切换到任务失败状态（5秒后自动回到 IDLE）
     */
    fun setErrorState() {
        ThreadUtils.runOnUiThread {
            progressHistory.recordError()
            setState(State.ERROR)
            scheduleAutoReset()
        }

    }

    /**
     * 设置状态
     */
    private fun setState(state: State) {
        currentState = state
        val view = EasyFloat.getFloatView(FLOAT_TAG)
        view?.let { updateStateView(it, state) }
    }

    /**
     * 更新视图状态
     */
    private fun updateStateView(view: View?, state: State) {
        if (view == null) return
        applyInteractionMode(view)

        val cardIdle = view.findViewById<View>(R.id.cardIdle)
        val cardTaskNotify = view.findViewById<View>(R.id.cardTaskNotify)
        val cardRunning = view.findViewById<View>(R.id.cardRunning)
        val cardSuccess = view.findViewById<View>(R.id.cardSuccess)
        val cardError = view.findViewById<View>(R.id.cardError)
        val cardLogPanel = view.findViewById<View>(R.id.cardLogPanel)
        val cursorOuter = view.findViewById<View>(R.id.cursorOuter)
        val cursorHorizontal = view.findViewById<View>(R.id.cursorHorizontal)
        val cursorVertical = view.findViewById<View>(R.id.cursorVertical)
        val cursorCore = view.findViewById<View>(R.id.cursorCore)
        val tvActionHint = view.findViewById<TextView>(R.id.tvActionHint)
        val isActionRunning = currentAction != null && currentChannel == null

        // 隐藏所有状态
        cardIdle?.visibility = View.GONE
        cardTaskNotify?.visibility = View.GONE
        cardRunning?.visibility = View.GONE
        cardSuccess?.visibility = View.GONE
        cardError?.visibility = View.GONE
        cardLogPanel?.visibility = View.GONE

        // 取消之前的自动重置
        cancelAutoReset()

        if (logPanelExpanded) {
            resetFloatTransform(view)
            cardLogPanel?.visibility = View.VISIBLE
            updateLogPanel(view, state)
            setFloatRootSize(
                view,
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT
            )
            return
        }

        // 显示对应状态
        when (state) {
            State.IDLE -> {
                resetFloatTransform(view)
                cardIdle?.visibility = View.VISIBLE
                setFloatRootWidth(view, getCircleWidth(view))
            }
            State.TASK_NOTIFY -> {
                resetFloatTransform(view)
                cardTaskNotify?.visibility = View.VISIBLE
                val tvNotify = view.findViewById<TextView>(R.id.tvTaskNotify)
                val app = appRef?.let(::localizedStringContext) ?: return
                val displayText = if (pendingTaskText.length > 40) {
                    pendingTaskText.substring(0, 40) + "..."
                } else {
                    pendingTaskText
                }
                tvNotify?.text = app.getString(R.string.floating_task_received, displayText)
                val ivLogo = view.findViewById<ImageView>(R.id.ivNotifyChannelLogo)
                ivLogo?.setImageResource(getChannelIcon(currentChannel))
                // 展开为 wrap_content
                setFloatRootWidth(view, WindowManager.LayoutParams.WRAP_CONTENT)
            }
            State.RUNNING -> {
                cancelNotifyCollapse()
                resetFloatTransform(view)
                // 收回为固定圆形
                setFloatRootWidth(view, getCircleWidth(view))
                cardRunning?.visibility = View.VISIBLE
                (cardRunning as? MaterialCardView)?.let { card ->
                    val app = appRef
                    val orbColor = if (app != null) {
                        ContextCompat.getColor(app, R.color.colorLumiOrbBase)
                    } else {
                        Color.parseColor("#FF06111D")
                    }
                    if (isActionRunning) {
                        val accentColor = if (app != null) {
                            ContextCompat.getColor(app, R.color.colorLumiGold)
                        } else {
                            Color.parseColor("#FFFFC857")
                        }
                        card.setCardBackgroundColor(orbColor)
                        card.setStrokeColor(accentColor)
                        card.strokeWidth = dp(3)
                    } else {
                        val ringColor = if (app != null) {
                            ContextCompat.getColor(app, R.color.colorLumiOrbStroke)
                        } else {
                            Color.parseColor("#FF119DFF")
                        }
                        card.setCardBackgroundColor(orbColor)
                        card.setStrokeColor(ringColor)
                        card.strokeWidth = dp(2)
                    }
                }
                cursorOuter?.visibility = if (isActionRunning) View.VISIBLE else View.GONE
                cursorHorizontal?.visibility = if (isActionRunning) View.VISIBLE else View.GONE
                cursorVertical?.visibility = if (isActionRunning) View.VISIBLE else View.GONE
                cursorCore?.visibility = if (isActionRunning) View.VISIBLE else View.GONE
                tvActionHint?.visibility = if (isActionRunning) View.VISIBLE else View.GONE
                tvActionHint?.text = actionHint(currentAction, currentTargetLabel, currentTraceId)
                // 更新轮数显示
                val tvRound = view.findViewById<TextView>(R.id.tvRound)
                tvRound?.text = currentBadge
                tvRound?.textSize = if (isActionRunning) 8f else 10f
                tvRound?.setTextColor(if (isActionRunning) Color.parseColor("#FFFFC857") else Color.WHITE)
                (tvRound?.layoutParams as? FrameLayout.LayoutParams)?.let { lp ->
                    lp.gravity = if (isActionRunning) {
                        Gravity.CENTER_HORIZONTAL or Gravity.TOP
                    } else {
                        Gravity.CENTER_HORIZONTAL or Gravity.BOTTOM
                    }
                    lp.topMargin = if (isActionRunning) dp(6) else 0
                    lp.bottomMargin = if (isActionRunning) 0 else dp(8)
                    tvRound.layoutParams = lp
                }
                val progressRunning = view.findViewById<View>(R.id.progressRunning)
                progressRunning?.visibility = if (isActionRunning) View.GONE else View.VISIBLE
                progressRunning?.alpha = 1f
                // 更新渠道 Logo
                val ivChannelLogo = view.findViewById<ImageView>(R.id.ivChannelLogo)
                ivChannelLogo?.visibility = if (isActionRunning) View.GONE else View.VISIBLE
                ivChannelLogo?.setImageResource(getChannelIcon(currentChannel))
            }
            State.SUCCESS -> {
                cancelNotifyCollapse()
                cardSuccess?.visibility = View.VISIBLE
                setFloatRootWidth(view, getCircleWidth(view))
            }
            State.ERROR -> {
                cancelNotifyCollapse()
                cardError?.visibility = View.VISIBLE
                setFloatRootWidth(view, getCircleWidth(view))
            }
        }
    }

    /**
     * 获取渠道对应的图标
     */
    private fun updateLogPanel(view: View, state: State) {
        val app = appRef?.let(::localizedStringContext) ?: return
        val recentLog = renderRecentLog(app)
        view.findViewById<TextView>(R.id.tvFloatLogTitle)?.text = app.getString(R.string.floating_log_title)
        val badge = if (state == State.IDLE && recentLog != null) {
            R.string.floating_state_recent
        } else {
            stateLabel(state)
        }
        view.findViewById<TextView>(R.id.tvFloatLogBadge)?.text = app.getString(badge)
        view.findViewById<TextView>(R.id.tvFloatLogBody)?.text = recentLog ?: when (state) {
            State.IDLE -> app.getString(R.string.floating_log_idle)
            State.TASK_NOTIFY -> app.getString(
                R.string.floating_log_received,
                pendingTaskText.truncateForFloat(72)
            )
            State.RUNNING -> {
                if (currentToolId != null) {
                    app.getString(
                        R.string.floating_log_tool,
                        app.getString(toolLabel(currentToolId.orEmpty()))
                    )
                } else if (currentAction != null && currentChannel == null) {
                    app.getString(
                        R.string.floating_log_action,
                        app.getString(actionLabel(currentAction.orEmpty())),
                        (currentTargetLabel ?: "--").truncateForFloat(32)
                    )
                } else {
                    app.getString(R.string.floating_log_running, currentRound.coerceAtLeast(1))
                }
            }
            State.SUCCESS -> app.getString(R.string.floating_log_success)
            State.ERROR -> app.getString(R.string.floating_log_error)
        }
        view.findViewById<TextView>(R.id.tvFloatLogHint)?.text = app.getString(
            if (isFloatingClickEnabled()) {
                R.string.floating_log_hint
            } else {
                R.string.floating_log_hint_passthrough
            }
        )
    }

    fun getRecentLog(context: Context): String? {
        return renderRecentLog(localizedStringContext(context))
    }

    private fun renderRecentLog(context: Context): String? {
        val entries = progressHistory.snapshot()
        if (entries.isEmpty()) return null
        return entries.joinToString("\n") { entry ->
            when (entry.kind) {
                FloatingProgressHistory.Kind.THINKING -> context.getString(
                    R.string.floating_history_thinking,
                    entry.stage
                )
                FloatingProgressHistory.Kind.TOOL -> context.getString(
                    R.string.floating_history_tool,
                    entry.stage,
                    context.getString(toolLabel(entry.value))
                )
                FloatingProgressHistory.Kind.SUCCESS -> context.getString(R.string.floating_history_success)
                FloatingProgressHistory.Kind.ERROR -> context.getString(R.string.floating_history_error)
            }
        }
    }

    private fun localizedStringContext(base: Context): Context {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return base
        val locales = base.getSystemService(LocaleManager::class.java)?.applicationLocales ?: return base
        if (locales.isEmpty) return base
        val configuration = Configuration(base.resources.configuration).apply {
            setLocales(locales)
        }
        return base.createConfigurationContext(configuration)
    }

    @StringRes
    private fun stateLabel(state: State): Int {
        return when (state) {
            State.IDLE -> R.string.floating_state_idle
            State.TASK_NOTIFY -> R.string.floating_state_received
            State.RUNNING -> R.string.floating_state_running
            State.SUCCESS -> R.string.floating_state_success
            State.ERROR -> R.string.floating_state_error
        }
    }

    @StringRes
    private fun toolLabel(toolId: String): Int {
        return when (toolId.lowercase(Locale.US)) {
            "open_app" -> R.string.floating_tool_open_app
            "get_screen_info" -> R.string.floating_tool_read_screen
            "tap", "click" -> R.string.floating_tool_tap
            "input_text", "type_text" -> R.string.floating_tool_input_text
            "swipe", "scroll_to_find" -> R.string.floating_tool_swipe
            "system_key", "press_key" -> R.string.floating_tool_system_key
            "screenshot", "take_screenshot" -> R.string.floating_tool_screenshot
            "finish" -> R.string.floating_tool_finish
            else -> R.string.floating_tool_other
        }
    }

    @StringRes
    private fun actionLabel(action: String): Int {
        return when (action.lowercase(Locale.US)) {
            "tap" -> R.string.floating_action_tap
            "long_press", "longpress" -> R.string.floating_action_long_press
            "swipe" -> R.string.floating_action_swipe
            "drag" -> R.string.floating_action_drag
            else -> R.string.floating_action_other
        }
    }

    private fun String.truncateForFloat(maxLength: Int): String {
        if (length <= maxLength) return this
        return take((maxLength - 3).coerceAtLeast(1)) + "..."
    }

    @DrawableRes
    private fun getChannelIcon(channel: Channel?): Int {
        return when (channel) {
            Channel.DINGTALK -> R.drawable.ic_channel_dingtalk
            Channel.FEISHU -> R.drawable.ic_channel_feishu
            Channel.QQ -> R.drawable.ic_channel_qq
            Channel.DISCORD -> R.drawable.ic_channel_discord
            Channel.TELEGRAM -> R.drawable.ic_channel_telegram
            Channel.WECHAT -> R.drawable.ic_channel_wechat
            else -> R.drawable.ic_lumi_agent_mark
        }
    }

    /**
     * 5秒后自动重置到 IDLE 状态
     */
    private fun scheduleAutoReset() {
        cancelAutoReset()
        autoResetRunnable = Runnable {
            setIdleState()
        }
        mainHandler.postDelayed(autoResetRunnable!!, AUTO_RESET_DELAY_MS)
    }

    /**
     * 取消自动重置
     */
    private fun cancelAutoReset() {
        autoResetRunnable?.let {
            mainHandler.removeCallbacks(it)
            autoResetRunnable = null
        }
    }

    private fun applyInteractionMode(view: View) {
        val mode = FloatingInteractionPolicy.resolve(isFloatingClickEnabled())
        val clickTarget = view.findViewById<View>(R.id.floatRoot) ?: view
        clickTarget.isClickable = mode.clickEnabled
        clickTarget.isLongClickable = false
        clickTarget.isFocusable = false
        if (mode.clickEnabled) {
            clickTarget.setOnClickListener { onFloatClick() }
        } else {
            clickTarget.setOnClickListener(null)
        }
        view.post {
            setFloatTouchPassthrough(view, mode.touchPassthrough, mode.windowAlpha)
        }
    }

    private fun setFloatTouchPassthrough(
        view: View,
        passthrough: Boolean,
        windowAlpha: Float
    ) {
        val (windowView, params) = findWindowHost(view) ?: return
        val nextFlags = if (passthrough) {
            params.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        } else {
            params.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
        }
        val nextAlpha = windowAlpha
        if (params.flags == nextFlags && params.alpha == nextAlpha) return
        params.flags = nextFlags
        params.alpha = nextAlpha
        runCatching {
            val wm = (appRef ?: return@runCatching).getSystemService(Context.WINDOW_SERVICE) as WindowManager
            wm.updateViewLayout(windowView, params)
        }.onFailure { error ->
            XLog.e("FloatingCircleManager", "Failed to update floating touch flags: ${error.message}")
        }
    }

    private fun findWindowHost(view: View): Pair<View, WindowManager.LayoutParams>? {
        var current: View? = view
        while (current != null) {
            val params = current.layoutParams
            if (params is WindowManager.LayoutParams) {
                return current to params
            }
            current = current.parent as? View
        }
        return null
    }

    /**
     * 确保悬浮窗在屏幕可见范围内，超出则修正
     */
    private fun ensureFloatInBounds(view: View) {
        val screenHeight = Resources.getSystem().displayMetrics.heightPixels
        val screenWidth = Resources.getSystem().displayMetrics.widthPixels
        // 获取导航栏高度，确保圆球不会被导航栏遮挡
        val navBarHeight = getNavigationBarHeight()

        // 方式1：尝试从 view 层级找到 WindowManager.LayoutParams
        var wmParams: WindowManager.LayoutParams? = null
        var wmView: View? = view
        while (wmView != null) {
            val lp = wmView.layoutParams
            if (lp is WindowManager.LayoutParams) {
                wmParams = lp
                break
            }
            wmView = wmView.parent as? View
        }

        if (wmParams != null) {
            val floatHeight = (wmView ?: view).height
            val floatWidth = (wmView ?: view).width
            val maxX = (screenWidth - floatWidth).coerceAtLeast(0)
            // 减去导航栏高度和额外安全边距
            val maxY = (screenHeight - floatHeight - navBarHeight - 50).coerceAtLeast(0)
            val clampedX = wmParams.x.coerceIn(0, maxX)
            val clampedY = wmParams.y.coerceIn(0, maxY)
            if (clampedX != wmParams.x || clampedY != wmParams.y) {
                EasyFloat.updateFloat(FLOAT_TAG, clampedX, clampedY)
            }
            savePosition(clampedX, clampedY)
            return
        }

        // 兜底：用 getLocationOnScreen 检测，updateFloat 修正
        val location = IntArray(2)
        view.getLocationOnScreen(location)
        val viewBottom = location[1] + view.height
        if (viewBottom > screenHeight - navBarHeight || location[1] < 0) {
            val safeY = screenHeight / 3
            EasyFloat.updateFloat(FLOAT_TAG, location[0].coerceIn(0, screenWidth), safeY)
            savePosition(location[0].coerceIn(0, screenWidth), safeY)
        } else {
            savePosition(location[0], location[1])
        }
    }

    private fun getNavigationBarHeight(): Int = BarUtils.getNavBarHeight()

    private fun moveToActionPoint(x: Int, y: Int) {
        val view = EasyFloat.getFloatView(FLOAT_TAG)
        if (view == null) {
            mainHandler.postDelayed({ moveToActionPoint(x, y) }, 120L)
            return
        }

        val (targetX, targetY) = actionPointToFloatTopLeft(view, x, y)
        EasyFloat.updateFloat(FLOAT_TAG, targetX, targetY)
    }

    private fun animateToActionPoint(x: Int, y: Int, durationMs: Long) {
        val view = EasyFloat.getFloatView(FLOAT_TAG)
        if (view == null) {
            mainHandler.postDelayed({ animateToActionPoint(x, y, durationMs) }, 120L)
            return
        }

        val location = IntArray(2)
        view.getLocationOnScreen(location)
        val startX = location[0]
        val startY = location[1]
        val (targetX, targetY) = actionPointToFloatTopLeft(view, x, y)

        moveAnimator?.cancel()
        moveAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = durationMs
            interpolator = AccelerateDecelerateInterpolator()
            addUpdateListener { animator ->
                val t = animator.animatedValue as Float
                val nextX = (startX + (targetX - startX) * t).toInt()
                val nextY = (startY + (targetY - startY) * t).toInt()
                EasyFloat.updateFloat(FLOAT_TAG, nextX, nextY)
            }
            start()
        }
    }

    private fun actionPointToFloatTopLeft(view: View, x: Int, y: Int): Pair<Int, Int> {
        val root = view.findViewById<View>(R.id.floatRoot)
        val fallbackSize = circleWidthPx.takeIf { it > 0 } ?: scaledCircleSizePx()
        val width = root?.width?.takeIf { it > 0 } ?: view.width.takeIf { it > 0 } ?: fallbackSize
        val height = root?.height?.takeIf { it > 0 } ?: view.height.takeIf { it > 0 } ?: fallbackSize
        val screenWidth = Resources.getSystem().displayMetrics.widthPixels
        val screenHeight = Resources.getSystem().displayMetrics.heightPixels
        val navBarHeight = getNavigationBarHeight()

        val targetX = (x - width / 2).coerceIn(0, (screenWidth - width).coerceAtLeast(0))
        val targetY = (y - height / 2).coerceIn(0, (screenHeight - height - navBarHeight - 20).coerceAtLeast(0))
        return targetX to targetY
    }

    private fun playActionPreviewAnimation(action: String) {
        val serial = ++visualSerial
        val view = EasyFloat.getFloatView(FLOAT_TAG)
        if (view == null) {
            mainHandler.postDelayed({ if (serial == visualSerial) playActionPreviewAnimation(action) }, 120L)
            return
        }

        val normalized = action.lowercase(Locale.US)
        view.animate().cancel()
        view.alpha = 1f
        view.scaleX = 1f
        view.scaleY = 1f
        view.pivotX = view.width / 2f
        view.pivotY = view.height / 2f

        val targetScale = when (normalized) {
            "long_press", "longpress" -> 1.32f
            "swipe", "drag" -> 1.18f
            else -> 1.24f
        }
        view.animate()
            .scaleX(targetScale)
            .scaleY(targetScale)
            .alpha(0.96f)
            .setDuration(150L)
            .setInterpolator(DecelerateInterpolator())
            .start()

        if (normalized == "tap") {
            mainHandler.postDelayed({
                if (serial != visualSerial) return@postDelayed
                view.animate()
                    .scaleX(1.08f)
                    .scaleY(1.08f)
                    .alpha(1f)
                    .setDuration(180L)
                    .setInterpolator(DecelerateInterpolator())
                    .start()
            }, 210L)
        }
    }

    private fun playResultAnimation() {
        val view = EasyFloat.getFloatView(FLOAT_TAG) ?: return
        view.animate().cancel()
        view.alpha = 1f
        view.scaleX = 1.34f
        view.scaleY = 1.34f
        view.animate()
            .scaleX(1f)
            .scaleY(1f)
            .alpha(1f)
            .setDuration(260L)
            .setInterpolator(DecelerateInterpolator())
            .start()
    }

    private fun resetFloatTransform(view: View) {
        view.animate().cancel()
        view.alpha = 1f
        view.scaleX = 1f
        view.scaleY = 1f
    }

    private fun actionBadge(action: String): String {
        return when (action.lowercase(Locale.US)) {
            "tap" -> "TAP"
            "long_press", "longpress" -> "HOLD"
            "swipe" -> "SWIPE"
            "drag" -> "DRAG"
            else -> "AI"
        }
    }

    /** 圆形状态的原始宽度（首次从 layout 读取并缓存） */
    private fun actionHint(action: String?, target: String?, traceId: String?): String {
        val name = when (action?.lowercase(Locale.US)) {
            "tap" -> "AI TAP"
            "long_press", "longpress" -> "AI HOLD"
            "swipe" -> "AI SWIPE"
            "drag" -> "AI DRAG"
            else -> "AI POINTER"
        }
        return name
    }

    private fun dp(value: Int): Int {
        return (value * Resources.getSystem().displayMetrics.density).toInt()
    }

    private fun pt(value: Float): Int {
        return TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_PT,
            value,
            Resources.getSystem().displayMetrics
        ).toInt()
    }

    private fun scaled(value: Int, scale: Float): Int {
        return (value * scale).toInt().coerceAtLeast(1)
    }

    private var baseLargeCircleWidthPx: Int = -1
    private var circleWidthPx: Int = -1

    private fun scaledCircleSizePx(): Int {
        val largePx = baseLargeCircleWidthPx.takeIf { it > 0 } ?: pt(76f)
        return scaled(largePx, getFloatingSize().scale)
    }

    private fun applyFloatingSize(view: View) {
        val root = view.findViewById<View>(R.id.floatRoot) ?: return
        val originalWidth = root.layoutParams?.width ?: root.width
        if (baseLargeCircleWidthPx <= 0 && originalWidth > 0 && originalWidth != ViewGroup.LayoutParams.WRAP_CONTENT) {
            baseLargeCircleWidthPx = originalWidth
        }

        val sizePx = scaledCircleSizePx()
        circleWidthPx = sizePx

        root.updateLayoutSize(sizePx, sizePx)
        listOf(
            R.id.cardIdle,
            R.id.cardRunning,
            R.id.cardSuccess,
            R.id.cardError
        ).forEach { id ->
            view.findViewById<View>(id)?.updateLayoutSize(sizePx, sizePx)
        }

        view.findViewById<View>(R.id.cardTaskNotify)?.updateLayoutHeight(sizePx)
        setCardRadius(view, R.id.cardIdle, sizePx / 2f)
        setCardRadius(view, R.id.cardRunning, sizePx / 2f)
        setCardRadius(view, R.id.cardSuccess, sizePx / 2f)
        setCardRadius(view, R.id.cardError, sizePx / 2f)
        setCardRadius(view, R.id.cardTaskNotify, sizePx / 2f)

        view.findViewById<View>(R.id.tvFloatTextIdle)?.updateLayoutSize((sizePx * 0.55f).toInt(), (sizePx * 0.55f).toInt())
        view.findViewById<View>(R.id.progressRunning)?.updateLayoutSize(sizePx, sizePx)
        view.findViewById<View>(R.id.cursorOuter)?.updateLayoutSize((sizePx * 0.87f).toInt(), (sizePx * 0.87f).toInt())
        view.findViewById<View>(R.id.cursorHorizontal)?.updateLayoutSize((sizePx * 0.71f).toInt(), (sizePx * 0.04f).toInt().coerceAtLeast(dp(2)))
        view.findViewById<View>(R.id.cursorVertical)?.updateLayoutSize((sizePx * 0.04f).toInt().coerceAtLeast(dp(2)), (sizePx * 0.71f).toInt())
        view.findViewById<View>(R.id.cursorCore)?.updateLayoutSize((sizePx * 0.17f).toInt(), (sizePx * 0.17f).toInt())
        view.findViewById<View>(R.id.ivChannelLogo)?.apply {
            updateLayoutSize((sizePx * 0.32f).toInt(), (sizePx * 0.32f).toInt())
            (layoutParams as? FrameLayout.LayoutParams)?.let { lp ->
                lp.topMargin = (sizePx * 0.13f).toInt()
                layoutParams = lp
            }
        }
        view.findViewById<View>(R.id.ivNotifyChannelLogo)?.updateLayoutSize((sizePx * 0.26f).toInt(), (sizePx * 0.26f).toInt())
    }

    private fun setCardRadius(view: View, id: Int, radius: Float) {
        (view.findViewById<View>(id) as? MaterialCardView)?.radius = radius
    }

    private fun View.updateLayoutSize(width: Int, height: Int) {
        val lp = layoutParams ?: return
        var changed = false
        if (lp.width != width) {
            lp.width = width
            changed = true
        }
        if (lp.height != height) {
            lp.height = height
            changed = true
        }
        if (changed) layoutParams = lp
    }

    private fun View.updateLayoutHeight(height: Int) {
        val lp = layoutParams ?: return
        if (lp.height != height) {
            lp.height = height
            layoutParams = lp
        }
    }

    /** 动态修改悬浮窗根布局宽度（展开胶囊 / 收回圆形） */
    private fun setFloatRootWidth(view: View, widthPx: Int) {
        val heightPx = if (widthPx == WindowManager.LayoutParams.WRAP_CONTENT) {
            getCircleWidth(view)
        } else {
            widthPx
        }
        setFloatRootSize(view, widthPx, heightPx)
    }

    private fun setFloatRootSize(view: View, widthPx: Int, heightPx: Int) {
        val root = view.findViewById<View>(R.id.floatRoot) ?: return
        val lp = root.layoutParams
        if (lp != null && (lp.width != widthPx || lp.height != heightPx)) {
            lp.width = widthPx
            lp.height = heightPx
            root.layoutParams = lp
        }
    }

    /** 获取圆形状态的宽度（createdResult 时缓存，确保与 XML 定义一致） */
    private fun getCircleWidth(@Suppress("UNUSED_PARAMETER") view: View): Int {
        return if (circleWidthPx > 0) circleWidthPx else WindowManager.LayoutParams.WRAP_CONTENT
    }


    /**
     * 保存位置
     */
    private fun savePosition(x: Int, y: Int) {
        KVUtils.putInt(KEY_FLOAT_X, x)
        KVUtils.putInt(KEY_FLOAT_Y, y)
    }

    /**
     * 获取保存的 X 坐标
     */
    private fun getSavedX(): Int? {
        val x = KVUtils.getInt(KEY_FLOAT_X, -1)
        return if (x == -1) null else x
    }

    /**
     * 获取保存的 Y 坐标
     */
    private fun getSavedY(): Int? {
        val y = KVUtils.getInt(KEY_FLOAT_Y, -1)
        return if (y == -1) null else y
    }

    /**
     * 点击回调，可以在外部设置
     */
    var onFloatClick: () -> Unit = { toggleLogPanel() }
}
