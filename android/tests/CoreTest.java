package com.dsefa.flir;

import java.util.*;
import java.nio.*;

/** No Android runtime required: tests the exact production protocol and renderer. */
public class CoreTest {
    static int checks;
    static void check(boolean ok, String message) {
        checks++; if (!ok) throw new AssertionError(message);
    }
    static byte[] frame(int thermal, int jpeg, int status, int residual) {
        ByteBuffer b = ByteBuffer.allocate(28+thermal+jpeg+status+residual).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0xBEEF); b.putInt(1); b.putInt(thermal+jpeg+status+residual);
        b.putInt(thermal); b.putInt(jpeg); b.putInt(status); b.putInt(0);
        if (thermal >= 39360) {
            for (int y=0;y<120;y++) for (int x=0;x<160;x++) {
                int p=32+y*328+(x<80?x*2:164+(x-80)*2);
                b.putShort(p, (short)(y*160+x+7000));
            }
        }
        return b.array();
    }
    public static void main(String[] args) throws Exception {
        byte[] ack=Protocol.link(0x40,1,2,0,new byte[0]);
        check(Arrays.equals(ack,Protocol.hex("ff5a0009400102005b")),"known iAP2 ACK bytes");
        byte[] payload=Protocol.hex("404000061d00");
        byte[] packet=Protocol.link(0x40,2,3,1,payload);
        check(Arrays.equals(Protocol.parseLink(packet).payload,payload),"payload checksum round trip");
        packet[9]^=1;
        check(Protocol.parseLink(packet)==null,"corrupt payload rejected");
        Protocol.LinkStream links=new Protocol.LinkStream();
        links.add(Protocol.hex("1234ff550200"),6);
        check(links.pop()==null,"partial detect buffered");
        byte[] tail=Protocol.hex("ee10"); links.add(tail,2);
        check(Arrays.equals(links.pop(),Protocol.DETECT),"fragmented detect reassembled");
        check(Arrays.equals(Protocol.csm(0xEA00,new int[]{0,1},new byte[][]{new byte[]{0},new byte[]{0,2}}),
            Protocol.hex("40400011ea000005000000000600010002")),"config EA exact bytes");

        FrameParser frames=new FrameParser(); byte[] f=frame(39852,5,150,7);
        frames.add(f,17); check(frames.pop()==null,"partial header buffered");
        frames.add(Arrays.copyOfRange(f,17,f.length-1),f.length-18);
        check(frames.pop()==null,"residual is part of authoritative record");
        frames.add(new byte[]{f[f.length-1]},1);
        FrameParser.Frame parsed=frames.pop();
        check(parsed.record.length==f.length && parsed.jpegOffset==39880,"dynamic JPEG offset and frame boundary");
        int[] raw=parsed.thermal();
        check(raw[0]==7000 && raw[80]==7080 && raw[19199]==26199,"VoSPI halves and row stride");
        byte[] bad=frame(39852,0,0,0); ByteBuffer.wrap(bad).order(ByteOrder.LITTLE_ENDIAN).putInt(8,10);
        frames.add(bad,bad.length); frames.add(f,f.length);
        check(frames.pop()!=null,"invalid section sum resynchronises");
        byte[] huge=frame(0,0,0,0); ByteBuffer.wrap(huge).order(ByteOrder.LITTLE_ENDIAN).putInt(8,Integer.MAX_VALUE);
        frames.add(huge,huge.length); frames.add(f,f.length);
        check(frames.pop()!=null,"oversized frame does not grow memory forever");
        byte[] unsupported=frame(0,0,1,0);frames.add(unsupported,unsupported.length);frames.add(f,f.length);
        check(frames.pop().thermalSize==39852,"short thermal record skipped without tearing down USB");

        List<byte[]> sent=new ArrayList<>(); List<Boolean> started=new ArrayList<>();
        IapSession session=new IapSession(sent::add,()->started.add(true));
        session.accept(Protocol.DETECT);
        check(Arrays.equals(sent.get(0),Protocol.DETECT),"DETECT echoed");
        session.accept(Protocol.link(0x80,7,0,0,new byte[]{1,2}));
        check(Protocol.parseLink(sent.get(1)).control==0xC0,"SYN ACK");
        session.accept(Protocol.link(0x40,7,1,0,new byte[0]));
        check(Protocol.csmId(Protocol.parseLink(sent.get(2)).payload)==0x1D00,"identification start");
        session.accept(Protocol.link(0x40,8,2,1,Protocol.csm(0x1D01)));
        check(Protocol.csmId(Protocol.parseLink(sent.get(sent.size()-1)).payload)==0x1D02,"identification accepted");
        session.accept(Protocol.link(0x40,8,3,0,new byte[0]));
        check(Protocol.csmId(Protocol.parseLink(sent.get(sent.size()-1)).payload)==0xAA00,"certificate request after ACK");
        session.accept(Protocol.link(0x40,9,4,1,Protocol.csm(0xAA01)));
        byte[] challenge=Protocol.parseLink(sent.get(sent.size()-1)).payload;
        check(Protocol.csmId(challenge)==0xAA02 && Protocol.param(challenge,0).length==20,"challenge request");
        session.accept(Protocol.link(0x40,10,5,1,Protocol.csm(0xAA03)));
        check(Protocol.csmId(Protocol.parseLink(sent.get(sent.size()-1)).payload)==0xAA05,"host auth acknowledgement");
        session.accept(Protocol.link(0x40,10,6,0,new byte[0]));
        check(started.size()==1,"config session opens frame stream");
        session.tick(31001);
        check(new String(Protocol.parseLink(sent.get(sent.size()-1)).payload).contains("autoFFC"),"keepalive config payload");
        check(Math.abs(Thermal.temperature(3000,.95,20,0)-22.513109271244332)<.0001,"exact desktop raw14 x4 / reflected radiometry");
        double[] uniform=new double[19200]; Arrays.fill(uniform,20);
        Thermal.Settings settings=new Thermal.Settings();
        int[] colors=Thermal.render(uniform,settings);
        check(colors.length==19200 && colors[0]==colors[19199],"uniform scene remains uniform");
        check(uniform[0]==20,"display does not mutate measurement data");
        System.out.println("PASS "+checks+" protocol/frame/session/render checks");
    }
}
