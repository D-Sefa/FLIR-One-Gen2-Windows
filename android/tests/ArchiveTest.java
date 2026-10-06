package com.dsefa.flir;
import java.io.*;
import java.util.*;
public class ArchiveTest {
    public static void main(String[] args)throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        RawArchive.Writer w=new RawArchive.Writer(bytes);int[] r=new int[19200];r[19199]=65535;r[0]=123;
        w.write(1700000000000L,r);w.write(1700000000125L,r);w.close();
        RawArchive.Reader reader=new RawArchive.Reader(new ByteArrayInputStream(bytes.toByteArray()));
        RawArchive.Sample first=reader.next();
        if(first.timestamp!=1700000000000L||first.raw[0]!=123||first.raw[19199]!=65535)throw new AssertionError("Lossless RAW/date round trip");
        if(reader.next().timestamp-first.timestamp!=125||reader.next()!=null)throw new AssertionError("Timing / clean EOF");
        boolean rejected=false;
        byte[] damaged=Arrays.copyOf(bytes.toByteArray(),bytes.size()-1);
        try(RawArchive.Reader rr=new RawArchive.Reader(new ByteArrayInputStream(damaged))){rr.next();rr.next();}catch(IOException e){rejected=true;}
        if(!rejected)throw new AssertionError("Truncated RAW archive must be rejected");
        System.out.println("PASS lossless archive, timestamps, EOF and corruption checks");
    }
}
