"""The plain WHOIS API's real response shape, with invented values.

SHAPE FROM A LIVE CALL, VALUES FROM NOWHERE. The response this was built
from named a real company, a real person's email address and a real
mobile number. This repository is public, so none of that is here: the
keys, the nesting and the quirks are reproduced exactly and every value
is fictional.

The three quirks are the point of keeping a fixture at all:

  * `registryData` carries NO registrant block. The populated one is at
    the top level, from the registrar's RDAP. A parser reading the
    registry tier finds nothing on a domain whose data is right there.

  * `dataError: MASKED_WHOIS_DATA` arrives WITH that populated block.
    Not a contradiction — the registry redacted contacts per the
    holder's disclosure preferences and the registrar's copy survived —
    but it means the names are not registry-verified.

  * `domainAvailability: "UNAVAILABLE"` means the domain IS REGISTERED.
    The exact opposite of what `unavailable` means everywhere else in
    this product, where it is a CheckStatus for "not examined".
"""

from __future__ import annotations

#: A thirty-year-old domain with a contactable registrant.
WHOIS_LIVE = {
    "WhoisRecord": {
        "createdDate": "1996-09-07T04:00:00Z",
        "updatedDate": "2026-08-08T15:02:00.358117Z",
        "expiresDate": "2027-09-06T04:00:00Z",
        "createdDateNormalized": "1996-09-07 04:00:00 UTC",
        "updatedDateNormalized": "2026-08-08 15:02:00 UTC",
        "expiresDateNormalized": "2027-09-06 04:00:00 UTC",
        "registrant": {
            "name": "EXAMPLE DAIRY COOPERATIVE",
            "street1": "12 Example Road",
            "city": "Anand",
            "state": "Gujarat",
            "postalCode": "388001",
            "country": "INDIA",
            "countryCode": "IN",
            "email": "registrant@example.invalid",
            "telephone": "910000000000",
        },
        "administrativeContact": {
            "name": "EXAMPLE DAIRY COOPERATIVE",
            "email": "registrant@example.invalid",
        },
        "domainName": "example-dairy.com",
        "nameServers": {
            "hostNames": ["ns1.example-dns.com", "ns2.example-dns.com"],
        },
        "status": "clientTransferProhibited",
        "parseCode": 123,
        "registrarName": "Example Registrar Ltd.",
        "registrarIANAID": "1495",
        "whoisServer": "https://rdapserver.invalid/",
        "dataError": "MASKED_WHOIS_DATA",
        "registryData": {
            "createdDate": "1996-09-07T04:00:00Z",
            "updatedDate": "2026-08-08T15:01:59Z",
            "expiresDate": "2027-09-06T04:00:00Z",
            "createdDateNormalized": "1996-09-07 04:00:00 UTC",
            "expiresDateNormalized": "2027-09-06 04:00:00 UTC",
            "domainName": "example-dairy.com",
            "nameServers": {
                "hostNames": ["ns1.example-dns.com", "ns2.example-dns.com"],
            },
            "status": "clientTransferProhibited",
            "parseCode": 127,
            "registrarName": "Example Registrar Ltd",
            "registrarIANAID": "1495",
            # NO registrant block. Deliberate — this is what the real
            # response looks like.
        },
        "contactEmail": "registrant@example.invalid",
        "domainAvailability": "UNAVAILABLE",
        "domainNameExt": ".com",
        "estimatedDomainAge": 11022,
    }
}

#: Registered last month, contacts fully redacted. The shape a shell
#: company presents, and the one the check exists to notice.
WHOIS_YOUNG_AND_PRIVATE = {
    "WhoisRecord": {
        "createdDate": "2026-10-02T09:14:00Z",
        "createdDateNormalized": "2026-10-02 09:14:00 UTC",
        "expiresDate": "2027-10-02T09:14:00Z",
        "expiresDateNormalized": "2027-10-02 09:14:00 UTC",
        "domainName": "example-newco.in",
        "nameServers": {"hostNames": ["ns1.example-dns.com"]},
        "status": "ok",
        "registrarName": "Example Registrar Ltd.",
        "dataError": "MASKED_WHOIS_DATA",
        "registryData": {
            "createdDate": "2026-10-02T09:14:00Z",
            "domainName": "example-newco.in",
        },
        "domainAvailability": "UNAVAILABLE",
        "estimatedDomainAge": 40,
    }
}

#: Never registered. `domainAvailability` flips, and there are no dates.
WHOIS_UNREGISTERED = {
    "WhoisRecord": {
        "domainName": "example-nothing-here.com",
        "domainAvailability": "AVAILABLE",
        "registryData": {"domainName": "example-nothing-here.com"},
    }
}
