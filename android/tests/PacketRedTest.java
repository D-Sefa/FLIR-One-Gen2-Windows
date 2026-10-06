package com.dsefa.flir;
import java.util.Arrays;
public class PacketRedTest {
    public static void main(String[] args) {
        byte[] expected={(byte)255,90,0,9,64,1,2,0,91};
        if(!Arrays.equals(expected,Protocol.link(64,1,2,0,new byte[0])))
            throw new AssertionError("Missing known-good iAP2 ACK encoder");
        System.out.println("PASS ACK encoder");
    }
}
