import { describe, expect, it } from "vitest";

import {
  arrayBufferToBase64url,
  base64urlToArrayBuffer,
  decodeCreationOptions,
  decodeRequestOptions,
  encodeAuthenticationCredential,
  encodeRegistrationCredential,
  isWebAuthnSupported,
} from "./webauthn";

function strToBytes(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

describe("base64url roundtrip", () => {
  it("encodes/decodes raw bytes без padding", () => {
    const raw = strToBytes("Hello, WebAuthn!");
    const encoded = arrayBufferToBase64url(raw);
    expect(encoded).not.toContain("=");
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    const decoded = new Uint8Array(base64urlToArrayBuffer(encoded));
    expect(Array.from(decoded)).toEqual(Array.from(raw));
  });

  it("handles empty input", () => {
    expect(arrayBufferToBase64url(new Uint8Array())).toBe("");
    expect(base64urlToArrayBuffer("").byteLength).toBe(0);
  });

  it("encodes binary bytes (включая non-ASCII)", () => {
    const raw = new Uint8Array([0xff, 0xfe, 0x00, 0xaa, 0x55]);
    const encoded = arrayBufferToBase64url(raw);
    const decoded = new Uint8Array(base64urlToArrayBuffer(encoded));
    expect(Array.from(decoded)).toEqual([0xff, 0xfe, 0x00, 0xaa, 0x55]);
  });
});

describe("decodeCreationOptions", () => {
  it("transforms base64url-string-encoded options → ArrayBuffer per spec", () => {
    const challengeBytes = new Uint8Array([1, 2, 3]);
    const userIdBytes = new Uint8Array([4, 5, 6]);
    const credIdBytes = new Uint8Array([7, 8, 9]);

    const serialised = {
      challenge: arrayBufferToBase64url(challengeBytes),
      rp: { id: "localhost", name: "Test" },
      user: {
        id: arrayBufferToBase64url(userIdBytes),
        name: "alice",
        displayName: "Alice",
      },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }],
      timeout: 60000,
      excludeCredentials: [
        { id: arrayBufferToBase64url(credIdBytes), type: "public-key", transports: ["usb"] },
      ],
    };

    const result = decodeCreationOptions(serialised);
    expect(new Uint8Array(result.challenge as ArrayBuffer)).toEqual(challengeBytes);
    expect(new Uint8Array(result.user.id as ArrayBuffer)).toEqual(userIdBytes);
    expect(result.user.name).toBe("alice");
    expect(result.excludeCredentials).toHaveLength(1);
    expect(
      new Uint8Array(result.excludeCredentials![0].id as ArrayBuffer),
    ).toEqual(credIdBytes);
    expect(result.excludeCredentials![0].transports).toEqual(["usb"]);
  });

  it("handles missing excludeCredentials gracefully", () => {
    const serialised = {
      challenge: arrayBufferToBase64url(new Uint8Array([1])),
      rp: { id: "localhost", name: "Test" },
      user: {
        id: arrayBufferToBase64url(new Uint8Array([2])),
        name: "alice",
        displayName: "alice",
      },
      pubKeyCredParams: [],
    };
    const result = decodeCreationOptions(serialised);
    expect(result.excludeCredentials).toEqual([]);
  });
});

describe("decodeRequestOptions", () => {
  it("transforms challenge + allowCredentials", () => {
    const challengeBytes = new Uint8Array([10, 20, 30]);
    const allowId = new Uint8Array([40, 50, 60]);
    const serialised = {
      challenge: arrayBufferToBase64url(challengeBytes),
      rpId: "localhost",
      userVerification: "preferred",
      allowCredentials: [
        { id: arrayBufferToBase64url(allowId), type: "public-key", transports: ["internal"] },
      ],
    };
    const result = decodeRequestOptions(serialised);
    expect(new Uint8Array(result.challenge as ArrayBuffer)).toEqual(challengeBytes);
    expect(result.userVerification).toBe("preferred");
    expect(result.allowCredentials).toHaveLength(1);
    expect(new Uint8Array(result.allowCredentials![0].id as ArrayBuffer)).toEqual(allowId);
  });
});

describe("encodeRegistrationCredential", () => {
  it("serialises rawId / clientDataJSON / attestationObject as base64url", () => {
    const rawIdBytes = new Uint8Array([1, 2, 3]);
    const clientDataBytes = strToBytes('{"challenge":"abc"}');
    const attestationBytes = new Uint8Array([0xaa, 0xbb]);
    const fakeCredential = {
      id: "abc",
      rawId: rawIdBytes.buffer,
      type: "public-key",
      response: {
        clientDataJSON: clientDataBytes.buffer,
        attestationObject: attestationBytes.buffer,
        getTransports: () => ["usb", "nfc"],
      },
      getClientExtensionResults: () => ({}),
    } as unknown as PublicKeyCredential;

    const encoded = encodeRegistrationCredential(fakeCredential);
    expect(encoded.id).toBe("abc");
    expect(encoded.type).toBe("public-key");
    expect(encoded.rawId).toBe(arrayBufferToBase64url(rawIdBytes));
    const response = encoded.response as Record<string, unknown>;
    expect(response.clientDataJSON).toBe(arrayBufferToBase64url(clientDataBytes));
    expect(response.attestationObject).toBe(arrayBufferToBase64url(attestationBytes));
    expect(response.transports).toEqual(["usb", "nfc"]);
  });

  it("handles missing getTransports() — fallback на пустой массив", () => {
    const fakeCredential = {
      id: "abc",
      rawId: new Uint8Array([1]).buffer,
      type: "public-key",
      response: {
        clientDataJSON: new Uint8Array([2]).buffer,
        attestationObject: new Uint8Array([3]).buffer,
        // No getTransports.
      },
      getClientExtensionResults: () => ({}),
    } as unknown as PublicKeyCredential;
    const encoded = encodeRegistrationCredential(fakeCredential);
    const response = encoded.response as Record<string, unknown>;
    expect(response.transports).toEqual([]);
  });
});

describe("encodeAuthenticationCredential", () => {
  it("serialises authenticatorData / signature / userHandle", () => {
    const fakeCredential = {
      id: "abc",
      rawId: new Uint8Array([1]).buffer,
      type: "public-key",
      response: {
        clientDataJSON: new Uint8Array([2]).buffer,
        authenticatorData: new Uint8Array([3, 4]).buffer,
        signature: new Uint8Array([5, 6, 7]).buffer,
        userHandle: new Uint8Array([8]).buffer,
      },
      getClientExtensionResults: () => ({}),
    } as unknown as PublicKeyCredential;
    const encoded = encodeAuthenticationCredential(fakeCredential);
    const response = encoded.response as Record<string, unknown>;
    expect(response.authenticatorData).toBe(arrayBufferToBase64url(new Uint8Array([3, 4])));
    expect(response.signature).toBe(arrayBufferToBase64url(new Uint8Array([5, 6, 7])));
    expect(response.userHandle).toBe(arrayBufferToBase64url(new Uint8Array([8])));
  });

  it("null userHandle passes through as null", () => {
    const fakeCredential = {
      id: "abc",
      rawId: new Uint8Array([1]).buffer,
      type: "public-key",
      response: {
        clientDataJSON: new Uint8Array([2]).buffer,
        authenticatorData: new Uint8Array([3]).buffer,
        signature: new Uint8Array([4]).buffer,
        userHandle: null,
      },
      getClientExtensionResults: () => ({}),
    } as unknown as PublicKeyCredential;
    const encoded = encodeAuthenticationCredential(fakeCredential);
    const response = encoded.response as Record<string, unknown>;
    expect(response.userHandle).toBeNull();
  });
});

describe("isWebAuthnSupported", () => {
  it("returns true в jsdom если PublicKeyCredential defined", () => {
    // jsdom is exposes window.navigator; PublicKeyCredential check
    // detects browser feature. Behaviour test-environment-specific —
    // smoke-asserting that helper не throw'ит.
    expect(typeof isWebAuthnSupported()).toBe("boolean");
  });
});
