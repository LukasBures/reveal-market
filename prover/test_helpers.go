package main

import "strconv"

func buildTestTickets() []ticket {
	tickets := make([]ticket, settlementBatchSize)
	for i := range tickets {
		tickets[i] = ticket{
			TicketID:  strconv.Itoa(i),
			OutcomeID: "0",
			Amount:    "0",
			User:      "0",
			Salt:      "0",
		}
	}
	return tickets
}

func buildTestRequest() settlementProofRequest {
	return settlementProofRequest{
		MarketID:          "0xabc",
		MerkleRoot:        "0x1",
		WinningOutcome:    "0",
		PoolTotals:        []string{"10", "0"},
		TotalEscrow:       "10",
		TotalLiability:    "9",
		RakeBps:           "50",
		CircuitHash:       "0x1",
		BatchIndex:        "0",
		CommitmentsCount:  "1",
		Tickets:           buildTestTickets(),
	}
}
