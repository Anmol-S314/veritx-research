// Simple saturating counter with overflow flag
// Formal property: counter should never exceed MAX
module counter #(
    parameter WIDTH = 4,
    parameter MAX   = 10
)(
    input  logic             clk,
    input  logic             rst_n,
    input  logic             en,
    output logic [WIDTH-1:0] count,
    output logic             overflow
);
    // known formal start state
    initial begin
        count    = '0;
        overflow = '0;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count    <= '0;
            overflow <= '0;
        end else if (en) begin
            if (count == MAX) begin
                overflow <= '1;
            end else begin
                count    <= count + 1;
                overflow <= '0;
            end
        end
    end

    always_comb assert(count <= MAX);
    // overflow is registered, so check the invariant it implies
    always_comb if (overflow) assert(count == MAX);
endmodule
