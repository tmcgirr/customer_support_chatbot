import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminApp from "./AdminApp";
import { AdminAuthError } from "./api";

const getDashboard = vi.fn();

vi.mock("./api", () => ({
  createAdminClient: () => ({
    getDashboard,
    listConversations: vi.fn().mockResolvedValue({ conversations: [] }),
    getConversation: vi.fn(),
    listRequests: vi.fn().mockResolvedValue({ requests: [] }),
    listUnresolved: vi.fn().mockResolvedValue({ questions: [] }),
  }),
  AdminAuthError: class AdminAuthError extends Error {},
}));

// Totals asserted below (42, 9, 3) are chosen so they don't also appear as a
// count inside the by_* breakdown tables.
const DASHBOARD = {
  conversations: { total: 42, by_status: { active: 40, closed: 2 }, by_outcome: { resolved: 30 } },
  requests: { total: 9, by_type: { strategy_call: 5, portal_support: 4 }, by_status: { received: 6, delivered: 4 } },
  unresolved_questions: 3,
};

function signIn() {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

afterEach(() => vi.clearAllMocks());

describe("AdminApp", () => {
  it("shows the login screen first", () => {
    render(<AdminApp />);
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the dashboard totals after a successful login", async () => {
    getDashboard.mockResolvedValue(DASHBOARD);
    render(<AdminApp />);

    signIn();

    // Stat totals render once creds verify and the Dashboard view loads.
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("shows an error message on invalid credentials", async () => {
    getDashboard.mockRejectedValue(new AdminAuthError());
    render(<AdminApp />);

    signIn();

    expect(await screen.findByText("Invalid admin credentials.")).toBeInTheDocument();
    // Still on the login screen.
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });
});
