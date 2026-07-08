import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminApp from "./AdminApp";
import { AdminAuthError } from "./api";

// Mock the whole API client. Each method is a shared vi.fn() so tests can set
// per-case resolved/rejected values; createAdminClient returns the same object.
const getMe = vi.fn();
const getDashboard = vi.fn();
const listConversations = vi.fn();
const getConversation = vi.fn();
const listRequests = vi.fn();
const listUnresolved = vi.fn();
const listCanonical = vi.fn();
const listAudit = vi.fn();
const revealRequest = vi.fn();
const revealConversation = vi.fn();
const redeliver = vi.fn();
const approveCanonical = vi.fn();

vi.mock("./api", () => ({
  createAdminClient: () => ({
    getMe,
    getDashboard,
    listConversations,
    getConversation,
    listRequests,
    listUnresolved,
    listCanonical,
    listAudit,
    revealRequest,
    revealConversation,
    redeliver,
    approveCanonical,
  }),
  AdminAuthError: class AdminAuthError extends Error {},
  AdminForbiddenError: class AdminForbiddenError extends Error {},
}));

// Totals asserted below (42, 9, 3) are chosen so they don't also appear as a
// count inside the by_* breakdown tables.
const DASHBOARD = {
  conversations: { total: 42, by_status: { active: 40, closed: 2 }, by_outcome: { resolved: 30 } },
  requests: {
    total: 9,
    by_type: { strategy_call: 5, portal_support: 4 },
    by_status: { received: 6, delivered: 4 },
  },
  unresolved_questions: 3,
};

const FAILED_REQUEST = {
  request_id: "req_1",
  type: "strategy_call",
  status: "delivery_failed",
  reference: "REF-1",
  contact_email: "j***@e***.com",
  contact_company: "Acme",
  conversation_id: "cnv_1",
  destination: "webhook",
  external_reference: "ext-1",
  last_delivery_error: "timeout",
  created_at: "2026-07-01",
};

const DRAFT_ANSWER = {
  intent: "pricing",
  name: "Pricing",
  status: "draft",
  owner: "ops",
  review_date: "2026-08-01",
};

function signIn() {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  // Sensible defaults; individual tests override role (getMe) as needed.
  getMe.mockResolvedValue({ username: "admin", role: "admin" });
  getDashboard.mockResolvedValue(DASHBOARD);
  listConversations.mockResolvedValue({ conversations: [] });
  listRequests.mockResolvedValue({ requests: [FAILED_REQUEST] });
  listUnresolved.mockResolvedValue({ questions: [] });
  listCanonical.mockResolvedValue({ answers: [DRAFT_ANSWER] });
  listAudit.mockResolvedValue({ entries: [] });
  revealRequest.mockResolvedValue({
    request_id: "req_1",
    contact: { name: "Jane Doe", email: "jane@example.com", company: "Acme" },
    fields: { message: "hello" },
  });
  redeliver.mockResolvedValue({ ok: true, detail: "queued" });
  approveCanonical.mockResolvedValue({ ok: true, detail: "approved" });
  vi.stubGlobal("prompt", vi.fn(() => "audit reason"));
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("AdminApp", () => {
  it("shows the login screen first", () => {
    render(<AdminApp />);
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the dashboard totals and identity after a successful login", async () => {
    render(<AdminApp />);
    signIn();

    // Stat totals render once creds verify (via getMe) and Dashboard loads.
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("admin (admin)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("shows an error message on invalid credentials", async () => {
    getMe.mockRejectedValue(new AdminAuthError());
    render(<AdminApp />);
    signIn();

    expect(await screen.findByText("Invalid admin credentials.")).toBeInTheDocument();
    // Still on the login screen.
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });

  it("hides privileged actions for a viewer but still shows the data", async () => {
    getMe.mockResolvedValue({ username: "vera", role: "viewer" });
    render(<AdminApp />);
    signIn();

    await screen.findByText("vera (viewer)");

    // Requests: data visible, but no Reveal / Redeliver buttons.
    fireEvent.click(screen.getByRole("button", { name: "Requests" }));
    expect(await screen.findByText("REF-1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reveal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Redeliver" })).not.toBeInTheDocument();

    // Knowledge: draft answer visible, but no Approve button.
    fireEvent.click(screen.getByRole("button", { name: "Knowledge" }));
    expect(await screen.findByText("Pricing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("shows privileged actions for an admin and reveals unmasked data", async () => {
    render(<AdminApp />);
    signIn();
    await screen.findByText("admin (admin)");

    fireEvent.click(screen.getByRole("button", { name: "Requests" }));

    // Admin sees both privileged actions on a delivery_failed row.
    const revealButton = await screen.findByRole("button", { name: "Reveal" });
    expect(screen.getByRole("button", { name: "Redeliver" })).toBeInTheDocument();

    // Clicking Reveal prompts for a reason and swaps the masked email cell for
    // the unmasked address (and shows the unmasked contact name inline).
    fireEvent.click(revealButton);
    expect(await screen.findByText("jane@example.com")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    expect(revealRequest).toHaveBeenCalledWith("req_1", "audit reason");

    // Knowledge: admin sees Approve on a draft answer.
    fireEvent.click(screen.getByRole("button", { name: "Knowledge" }));
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
  });
});
