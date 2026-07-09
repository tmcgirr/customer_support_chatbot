import "@testing-library/jest-dom";
import { afterEach, beforeEach } from "vitest";

// The widget persists its session in sessionStorage (V7 reconnect). Clear it around
// every test so one test's stored session never makes the next test try to resume.
beforeEach(() => window.sessionStorage.clear());
afterEach(() => window.sessionStorage.clear());
