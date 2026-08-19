// Round-robin arbiter with formal safety properties
module arbiter #(
    parameter PORTS = 4
)(
    input  logic             clk,
    input  logic             rst_n,
    input  logic [PORTS-1:0] request,
    output logic [PORTS-1:0] grant
);
    logic [$clog2(PORTS)-1:0] rr_ptr;    // `priority` is a reserved keyword
    logic [PORTS-1:0]         request_q; // grant is registered, so it lags request

    initial begin
        grant     = '0;
        rr_ptr    = '0;
        request_q = '0;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            grant     <= '0;
            rr_ptr    <= '0;
            request_q <= '0;
        end else begin
            int   idx;
            logic found;
            request_q <= request;
            grant     <= '0;
            found      = 1'b0;
            for (int i = 0; i < PORTS; i++) begin
                idx = (rr_ptr + i) % PORTS;
                if (!found && request[idx]) begin
                    grant[idx] <= '1;
                    rr_ptr     <= idx + 1;
                    found       = 1'b1;
                end
            end
        end
    end

    // mutual exclusion: at most one grant
    always_comb assert($onehot0(grant));
    // grant only to a port that requested (previous cycle)
    always_comb assert((grant & ~request_q) == '0);
endmodule
