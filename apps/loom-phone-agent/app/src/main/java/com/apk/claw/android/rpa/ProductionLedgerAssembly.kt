package com.apk.claw.android.rpa

import java.io.File

internal class ProductionLedgerAssembly private constructor(
    private val store: ActionLedgerStore,
    internal val workflowTemplateRoot: File,
    val resumeProofVerifier: ActionLedgerResumeProofVerifier,
    private val clock: () -> Long
) {
    fun singleDispatchExecutor(
        dispatcher: ActionDispatcher,
        verifier: OutcomeVerifier,
        generation: () -> GenerationSnapshot?
    ): SingleDispatchExecutor = SingleDispatchExecutor(
        store = store,
        dispatcher = dispatcher,
        verifier = verifier,
        clock = clock,
        generation = generation,
        postDispatchGenerationPolicy = ProductionPostDispatchGenerationPolicy
    )

    companion object {
        private const val WORKFLOW_TEMPLATES_DIRECTORY = "workflow_templates"

        fun create(
            filesDirectory: File,
            clock: () -> Long = System::currentTimeMillis
        ): ProductionLedgerAssembly {
            val filesRoot = filesDirectory.canonicalFile
            val templateRoot = File(filesRoot, WORKFLOW_TEMPLATES_DIRECTORY).canonicalFile
            require(templateRoot.parentFile == filesRoot) { "workflow_templates_root_invalid" }
            val store = ActionLedgerStore(templateRoot, clock = clock)
            return ProductionLedgerAssembly(
                store = store,
                workflowTemplateRoot = templateRoot,
                resumeProofVerifier = ActionLedgerResumeProofVerifier(store),
                clock = clock
            )
        }
    }
}
