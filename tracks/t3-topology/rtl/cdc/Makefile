# CDC FIFO test build (Verilator)
VERILATOR = verilator
all: Vcdc_fifo
Vcdc_fifo: cdc_fifo.sv tb_cdc.cpp
	$(VERILATOR) --timing -O0 -Wall -Wno-fatal -Wno-WIDTH -Wno-UNOPTFLAT \
	  --cc --exe --build --top-module cdc_fifo --Mdir obj_dir tb_cdc.cpp cdc_fifo.sv
run: Vcdc_fifo
	./obj_dir/Vcdc_fifo
clean:
	rm -rf obj_dir