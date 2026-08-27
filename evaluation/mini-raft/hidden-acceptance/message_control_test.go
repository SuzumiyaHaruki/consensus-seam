package acceptance_test

import (
	"errors"
	"testing"

	raft "github.com/SuzumiyaHaruki/mini-raft"
)

type rejectingTransport struct {
	err error
}

func (transport rejectingTransport) Send(raft.Message) error {
	return transport.err
}

func newNodes(
	t *testing.T,
	transport raft.Transport,
	network *raft.MemoryTransport,
) map[uint64]*raft.Node {
	t.Helper()
	nodes := make(map[uint64]*raft.Node)
	for id := uint64(1); id <= 3; id++ {
		peers := make([]uint64, 0, 2)
		for peer := uint64(1); peer <= 3; peer++ {
			if peer != id {
				peers = append(peers, peer)
			}
		}
		node, err := raft.NewNode(raft.Config{
			ID: id, Peers: peers, ElectionTick: 4, HeartbeatTick: 1,
			Transport: transport,
		})
		if err != nil {
			t.Fatalf("NewNode(%d): %v", id, err)
		}
		nodes[id] = node
		network.Register(node)
	}
	return nodes
}

func TestMC1Capture(t *testing.T) {
	network := raft.NewMemoryTransport()
	controller := raft.NewMessageController(network)
	nodes := newNodes(t, controller, network)
	for tick := 0; tick < 16 && len(controller.ListPending()) == 0; tick++ {
		if err := nodes[1].Tick(); err != nil {
			t.Fatalf("Tick: %v", err)
		}
	}
	pending := controller.ListPending()
	if len(pending) != 2 {
		t.Fatalf("pending count = %d, want 2 vote requests", len(pending))
	}
	if pending[0].ID == pending[1].ID || pending[0].CaptureSequence >= pending[1].CaptureSequence {
		t.Fatalf("message identity/order is not stable: %+v", pending)
	}
	controller.ClearPending()
	if remaining := controller.ListPending(); len(remaining) != 0 {
		t.Fatalf("ClearPending left messages: %+v", remaining)
	}
}

func TestMC2Suppression(t *testing.T) {
	network := raft.NewMemoryTransport()
	controller := raft.NewMessageController(network)
	nodes := newNodes(t, controller, network)
	for tick := 0; tick < 16 && len(controller.ListPending()) == 0; tick++ {
		if err := nodes[1].Tick(); err != nil {
			t.Fatalf("Tick: %v", err)
		}
	}
	for _, id := range []uint64{2, 3} {
		if status := nodes[id].Status(); status.Term != 0 {
			t.Fatalf("node %d processed a message before Inject: %+v", id, status)
		}
	}
}

func TestMC3ExactInjection(t *testing.T) {
	network := raft.NewMemoryTransport()
	controller := raft.NewMessageController(network)
	nodes := newNodes(t, controller, network)
	for tick := 0; tick < 16 && len(controller.ListPending()) == 0; tick++ {
		if err := nodes[1].Tick(); err != nil {
			t.Fatalf("Tick: %v", err)
		}
	}
	pending := controller.ListPending()
	if len(pending) != 2 {
		t.Fatalf("pending count = %d, want 2", len(pending))
	}
	first, second := pending[0], pending[1]
	if second.To != 3 {
		first, second = second, first
	}
	if second.To != 3 {
		t.Fatalf("no pending request targets node 3: %+v", pending)
	}
	if err := controller.Inject(second.ID); err != nil {
		t.Fatalf("Inject(%q): %v", second.ID, err)
	}
	remaining := controller.ListPending()
	foundFirst := false
	for _, message := range remaining {
		if message.ID == second.ID {
			t.Fatalf("injected message %q remains pending", second.ID)
		}
		if message.ID == first.ID {
			foundFirst = true
		}
	}
	if !foundFirst {
		t.Fatalf("unselected message %q was consumed: %+v", first.ID, remaining)
	}
	if status := nodes[3].Status(); status.Term == 0 {
		t.Fatalf("selected target did not process injected message: %+v", status)
	}
	if status := nodes[2].Status(); status.Term != 0 {
		t.Fatalf("unselected target processed a message: %+v", status)
	}
}


func TestMC4FailedDeliveryRetention(t *testing.T) {
	deliveryError := errors.New("injected delivery failed")
	rejecting := raft.NewMessageController(rejectingTransport{err: deliveryError})
	if err := rejecting.Send(raft.Message{
		From: 1, To: 2, Type: raft.MessageRequestVote, Term: 1,
	}); err != nil {
		t.Fatalf("capture before failed injection: %v", err)
	}
	failedPending := rejecting.ListPending()
	failedID := failedPending[0].ID
	if err := rejecting.Inject(failedID); !errors.Is(err, deliveryError) {
		t.Fatalf("Inject(%q) error = %v, want %v", failedID, err, deliveryError)
	}
	stillPending := rejecting.ListPending()
	if len(stillPending) != 1 || stillPending[0].ID != failedID {
		t.Fatalf("failed injection consumed pending message: %+v", stillPending)
	}
}
