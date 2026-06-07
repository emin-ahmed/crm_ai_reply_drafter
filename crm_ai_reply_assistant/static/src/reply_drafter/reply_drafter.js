/** @odoo-module **/
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

/**
 * Form field component for the AI Reply Drafter wizard.
 *
 * On mount it opens an SSE connection to the streaming controller and renders
 * the draft live as tokens arrive. The authoritative draft, token counts and
 * cost are written to the wizard record server-side when the stream ends; this
 * component reloads the record afterwards so the footer "Use this draft" button
 * (gated on the wizard's state) becomes available.
 */
export class ReplyDrafter extends Component {
    static template = "crm_ai_reply_assistant.ReplyDrafter";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({
            status: "streaming", // streaming | done | error
            text: "",
            error: "",
        });
        this.source = null;

        onMounted(() => this.start());
        onWillUnmount(() => this.close());
    }

    get wizardId() {
        return this.props.record.resId;
    }

    /** Open the SSE stream for this wizard. */
    start() {
        this.close();
        this.state.status = "streaming";
        this.state.text = "";
        this.state.error = "";

        const url = `/crm_ai_reply_assistant/stream?wizard_id=${this.wizardId}`;
        const source = new EventSource(url);
        this.source = source;

        source.addEventListener("chunk", (ev) => {
            try {
                this.state.text += JSON.parse(ev.data).text;
            } catch {
                // ignore malformed frame
            }
        });

        source.addEventListener("done", async (ev) => {
            this.close();
            let usage = {};
            try {
                usage = JSON.parse(ev.data) || {};
            } catch {
                usage = {};
            }
            // Write the draft + status onto the wizard record from the client so
            // the footer Send/Edit buttons (gated on `state`) reliably appear and
            // the (possibly edited) text is what gets sent — independent of the
            // server-side persistence timing. The controller still writes the
            // audit log with token counts/cost.
            await this.props.record.update({
                [this.props.name]: this.state.text,
                state: "done",
                input_tokens: usage.input_tokens || 0,
                output_tokens: usage.output_tokens || 0,
            });
            this.state.status = "done";
        });

        source.addEventListener("error", (ev) => {
            // Named server error frame carries a message; a bare connection
            // error (e.g. stream closed) does not.
            let message = "";
            if (ev.data) {
                try {
                    message = JSON.parse(ev.data).message;
                } catch {
                    message = "";
                }
            }
            // A connection error after we're already done is just the stream
            // closing — ignore it.
            if (this.state.status === "done") {
                return;
            }
            this.close();
            this.state.status = "error";
            this.state.error =
                message || _t("The draft could not be generated. Please try again.");
        });
    }

    /** Persist in-popup edits back to the wizard record. */
    onInput(ev) {
        this.state.text = ev.target.value;
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    /** Re-run generation from scratch. */
    regenerate() {
        this.start();
    }

    close() {
        if (this.source) {
            this.source.close();
            this.source = null;
        }
    }
}

export const replyDrafter = {
    component: ReplyDrafter,
    supportedTypes: ["text"],
};

registry.category("fields").add("reply_drafter", replyDrafter);
