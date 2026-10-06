package com.dsefa.flir;

import java.io.ByteArrayOutputStream;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.CRC32;

public final class Protocol {
    public static final byte[] DETECT=hex("ff550200ee10");
    public static byte[] hex(String s) {
        s=s.replace(" ",""); byte[] b=new byte[s.length()/2];
        for(int i=0;i<b.length;i++) b[i]=(byte)Integer.parseInt(s.substring(2*i,2*i+2),16);
        return b;
    }
    public static int u(byte b) { return b&255; }
    public static int be16(byte[] b,int p) { return (u(b[p])<<8)|u(b[p+1]); }
    public static long le32(byte[] b,int p) { return (long)u(b[p])|((long)u(b[p+1])<<8)|((long)u(b[p+2])<<16)|((long)u(b[p+3])<<24); }
    static int sum(byte[] b,int start,int end) { int s=0;for(int i=start;i<end;i++)s+=u(b[i]);return s&255; }
    static void be16(byte[] b,int p,int n) { b[p]=(byte)(n>>8);b[p+1]=(byte)n; }
    public static byte[] link(int control,int seq,int ack,int session,byte[] payload) {
        if(payload.length>65525)throw new IllegalArgumentException("iAP2 payload too large");
        int size=payload.length==0?9:payload.length+10;
        byte[] p=new byte[size];p[0]=(byte)255;p[1]=90;be16(p,2,size);
        p[4]=(byte)control;p[5]=(byte)seq;p[6]=(byte)ack;p[7]=(byte)session;
        p[8]=(byte)-sum(p,0,8);
        if(payload.length>0){System.arraycopy(payload,0,p,9,payload.length);p[size-1]=(byte)-sum(payload,0,payload.length);}
        return p;
    }
    public static final class Link {
        public int control,seq,ack,session; public byte[] payload;
    }
    public static Link parseLink(byte[] p) {
        if(p.length<9||u(p[0])!=255||p[1]!=90||be16(p,2)!=p.length||sum(p,0,9)!=0)return null;
        if(p.length>9&&sum(p,9,p.length)!=0)return null;
        Link l=new Link();l.control=u(p[4]);l.seq=u(p[5]);l.ack=u(p[6]);l.session=u(p[7]);
        l.payload=p.length>9?Arrays.copyOfRange(p,9,p.length-1):new byte[0];return l;
    }
    public static byte[] csm(int id){return csm(id,new int[0],new byte[0][]);}
    public static byte[] csm(int id,int[] ids,byte[][] values) {
        int size=6;for(byte[] v:values)size+=v.length+4;
        if(size>65525||ids.length!=values.length)throw new IllegalArgumentException("Invalid CSM");
        byte[] b=new byte[size];b[0]=64;b[1]=64;be16(b,2,size);be16(b,4,id);int p=6;
        for(int i=0;i<ids.length;i++){be16(b,p,values[i].length+4);be16(b,p+2,ids[i]);System.arraycopy(values[i],0,b,p+4,values[i].length);p+=4+values[i].length;}
        return b;
    }
    public static int csmId(byte[] p){return p.length>=6?be16(p,4):-1;}
    public static byte[] param(byte[] p,int id) {
        for(int i=6;i+4<=p.length;){int n=be16(p,i);if(n<4||i+n>p.length)return new byte[0];
            if(be16(p,i+2)==id)return Arrays.copyOfRange(p,i+4,i+n);i+=n;}
        return new byte[0];
    }
    public static byte[] keepalive(int transfer) {
        byte[] body="{\"type\":\"setOption\",\"data\":{\"autoFFC\":true}}\u0000".getBytes(StandardCharsets.UTF_8);
        ByteBuffer h=ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN);h.putInt(0x1CC).putInt(1).putInt(body.length);
        CRC32 crc=new CRC32();crc.update(h.array());
        ByteBuffer b=ByteBuffer.allocate(body.length+18).order(ByteOrder.LITTLE_ENDIAN);
        b.put((byte)(transfer>>8)).put((byte)transfer).put(h.array()).putInt((int)crc.getValue()).put(body);return b.array();
    }
    static final class Buffer {
        byte[] data=new byte[4096]; int length;
        void add(byte[] b,int n){if(n<0||n>b.length)throw new IllegalArgumentException();
            if(length+n>4*1024*1024)throw new IllegalArgumentException("USB buffer exceeds bound");
            if(length+n>data.length)data=Arrays.copyOf(data,Math.max(length+n,data.length*2));
            System.arraycopy(b,0,data,length,n);length+=n;}
        void drop(int n){System.arraycopy(data,n,data,0,length-n);length-=n;}
        byte[] take(int n){byte[] b=Arrays.copyOf(data,n);drop(n);return b;}
        int find(byte[] magic){outer:for(int i=0;i<=length-magic.length;i++){
            for(int j=0;j<magic.length;j++)if(data[i+j]!=magic[j])continue outer;return i;}return -1;}
    }
    public static final class LinkStream {
        final Buffer b=new Buffer();
        public void add(byte[] data,int n){b.add(data,n);}
        public byte[] pop(){while(b.length>0){int d=b.find(DETECT),l=b.find(new byte[]{(byte)255,90});
            int pos=d<0?l:l<0?d:Math.min(d,l);
            if(pos<0){if(b.length>8)b.drop(b.length-8);return null;}
            if(pos>0)b.drop(pos);
            if(d==pos){return b.take(DETECT.length);}
            if(b.length<9)return null;
            int n=be16(b.data,2);if(n<9||sum(b.data,0,9)!=0){b.drop(1);continue;}
            if(b.length<n)return null;
            if(n>9&&sum(b.data,9,n)!=0){b.drop(1);continue;}
            return b.take(n);
        }return null;}
    }
}
